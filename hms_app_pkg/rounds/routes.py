# hms_app_pkg/rounds/routes.py
from flask import Blueprint, request, jsonify, current_app, g # Import g
from .. import db
from ..models import RoundingNote, Patient, User # Make sure all are imported
from ..utils import permission_required # Using our centralized decorator
from sqlalchemy.exc import IntegrityError
from datetime import datetime # Python's datetime

rounds_bp = Blueprint('rounds_bp', __name__) # Consistent blueprint naming

# The local get_user_id_from_token_for_rounds() helper is removed.
# We will use g.current_user set by the permission_required decorator.

@rounds_bp.route('/patients/<string:patient_id>/rounding-notes', methods=['POST'])
@permission_required('rounding_note:create')
def create_rounding_note(patient_id):
    current_user = g.current_user # User performing the action

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided."}), 400

    # Validate patient exists
    if not Patient.query.get(patient_id):
        return jsonify({"error": "Patient not found."}), 404

    # rounding_physician_id can be different from the user creating the note (e.g., a resident entering for an attending)
    # If not provided, default to the user creating the note.
    rounding_physician_id_from_payload = data.get('rounding_physician_id', current_user.id)
    
    if not User.query.get(rounding_physician_id_from_payload):
        return jsonify({"error": "Specified rounding_physician_id not found."}), 400

    rounding_datetime_val = datetime.utcnow() # Default
    if data.get('rounding_datetime'):
        try:
            rounding_datetime_val = datetime.fromisoformat(data['rounding_datetime'].replace('Z', '+00:00'))
        except ValueError:
            return jsonify({"error": "Invalid rounding_datetime format. Use ISO format."}), 400
    
    # Ensure all required fields for your model are present or have defaults
    # For example, if 'subjective', 'objective', 'assessment', 'plan' are mandatory
    # for a new note, add checks here. Assuming they are optional (nullable=True in model).

    try:
        note = RoundingNote(
            patient_id=patient_id,
            rounding_physician_id=rounding_physician_id_from_payload,
            # created_by_user_id might be useful if different from rounding_physician_id,
            # but RoundingNote model doesn't have it. Assuming rounding_physician_id is the key author.
            rounding_datetime=rounding_datetime_val,
            subjective=data.get('subjective'),
            objective=data.get('objective'),
            assessment=data.get('assessment'),
            plan=data.get('plan'),
            is_finalized=data.get('is_finalized', False), # Default to not finalized
            priority=data.get('priority'),
            duration_minutes=data.get('duration_minutes'),
            location=data.get('location')
        )
        db.session.add(note)
        db.session.commit()
        return jsonify(note.to_dict()), 201
    except IntegrityError:
        db.session.rollback()
        current_app.logger.error("Integrity error creating rounding note.")
        return jsonify({"error": "Database integrity error."}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating rounding note: {e}")
        return jsonify({"error": "Could not create rounding note."}), 500

@rounds_bp.route('/rounding-notes/<string:note_id>', methods=['GET'])
@permission_required('rounding_note:read') # Base permission
def get_rounding_note(note_id):
    note = RoundingNote.query.get_or_404(note_id)
    current_user = g.current_user
    
    # Authorization: Can user see this specific note?
    # Based on patient access, or if they are physician/reviewer, or have 'rounding_note:read:any'
    # This is a simplified check. Real-world might involve checking patient team membership.
    can_read_any = 'rounding_note:read:any' in current_user.get_permissions() # Assuming get_permissions() works on User object
    
    if not (note.rounding_physician_id == current_user.id or \
            note.reviewed_by_id == current_user.id or \
            can_read_any):
        # Check if user can access the patient associated with this note
        # This requires a more complex function like: user_can_access_patient(current_user.id, note.patient_id)
        # For now, if not directly involved or admin, deny.
        # A basic patient access check could be:
        # patient_of_note = Patient.query.get(note.patient_id)
        # if not (patient_of_note and (patient_of_note.attending_physician_id == current_user.id or can_read_any)):
        return jsonify({"error": "Unauthorized to view this rounding note."}), 403
            
    return jsonify(note.to_dict())

@rounds_bp.route('/patients/<string:patient_id>/rounding-notes', methods=['GET'])
@permission_required('rounding_note:read')
def list_rounding_notes_for_patient(patient_id):
    Patient.query.get_or_404(patient_id) # Ensure patient exists
    current_user = g.current_user

    # Authorization: Can user see notes for this patient? (Simplified)
    # if not user_can_access_patient(current_user.id, patient_id) and \
    #    'rounding_note:read:any' not in current_user.get_permissions():
    #    return jsonify({"error": "Unauthorized to view rounding notes for this patient."}), 403

    physician_id_filter = request.args.get('rounding_physician_id')
    is_finalized_str = request.args.get('is_finalized')
    priority_filter = request.args.get('priority')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    query = RoundingNote.query.filter_by(patient_id=patient_id)

    if physician_id_filter:
        query = query.filter_by(rounding_physician_id=physician_id_filter)
    if is_finalized_str is not None:
        is_finalized_val = is_finalized_str.lower() in ('true', '1')
        query = query.filter_by(is_finalized=is_finalized_val)
    if priority_filter:
        query = query.filter(RoundingNote.priority.ilike(f'%{priority_filter}%'))
    if start_date_str:
        try:
            query = query.filter(RoundingNote.rounding_datetime >= datetime.fromisoformat(start_date_str.replace('Z', '+00:00')))
        except ValueError: return jsonify({"error": "Invalid start_date format"}), 400
    if end_date_str:
        try:
            query = query.filter(RoundingNote.rounding_datetime <= datetime.fromisoformat(end_date_str.replace('Z', '+00:00')))
        except ValueError: return jsonify({"error": "Invalid end_date format"}), 400
            
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    notes_pagination = query.order_by(RoundingNote.rounding_datetime.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        "rounding_notes": [note.to_dict() for note in notes_pagination.items],
        "total": notes_pagination.total,
        "page": notes_pagination.page,
        "per_page": notes_pagination.per_page,
        "pages": notes_pagination.pages
    }), 200


@rounds_bp.route('/rounding-notes/<string:note_id>', methods=['PUT'])
@permission_required('rounding_note:update') # Could be 'rounding_note:update:own'
def update_rounding_note(note_id):
    current_user = g.current_user
    note = RoundingNote.query.get_or_404(note_id)
    
    can_update_any = 'rounding_note:update:any' in current_user.get_permissions()
    can_update_finalized = 'rounding_note:update:finalized' in current_user.get_permissions()

    if not (note.rounding_physician_id == current_user.id or can_update_any):
        return jsonify({"error": "Unauthorized: You are not the author or lack privileges."}), 403
    
    if note.is_finalized and not (can_update_finalized or can_update_any):
        return jsonify({"error": "Cannot update a finalized note without specific privileges."}), 403

    data = request.json
    if not data: return jsonify({"error": "No update data provided."}), 400

    fields_to_update = ['subjective', 'objective', 'assessment', 'plan', 
                        'priority', 'duration_minutes', 'location']
    for field in fields_to_update:
        if field in data:
            setattr(note, field, data[field])
    
    if 'rounding_datetime' in data and data.get('rounding_datetime'):
        try:
            note.rounding_datetime = datetime.fromisoformat(data['rounding_datetime'].replace('Z', '+00:00'))
        except ValueError: return jsonify({"error": "Invalid rounding_datetime format for update."}), 400
    
    # Allow updating 'is_finalized' only if user has specific permission or it's part of 'finalize' endpoint
    if 'is_finalized' in data and isinstance(data['is_finalized'], bool):
        if data['is_finalized'] and not note.is_finalized: # Finalizing
            if not (note.rounding_physician_id == current_user.id or 'rounding_note:finalize:any' in current_user.get_permissions()):
                return jsonify({"error": "Unauthorized to finalize this note."}), 403
            note.is_finalized = True
        elif not data['is_finalized'] and note.is_finalized: # Un-finalizing (needs strong permission)
            if not ('rounding_note:update:finalized' in current_user.get_permissions() or can_update_any):
                 return jsonify({"error": "Unauthorized to un-finalize this note."}), 403
            note.is_finalized = False

    note.updated_at = datetime.utcnow() # Explicitly update timestamp
    db.session.commit()
    return jsonify({"message": "RoundingNote updated", "rounding_note": note.to_dict()})

@rounds_bp.route('/rounding-notes/<string:note_id>/finalize', methods=['POST'])
@permission_required('rounding_note:finalize') # Or 'rounding_note:finalize:own'
def finalize_rounding_note(note_id):
    current_user = g.current_user
    note = RoundingNote.query.get_or_404(note_id)

    if note.is_finalized:
        return jsonify({"message": "RoundingNote already finalized."}), 400
        
    can_finalize_any = 'rounding_note:finalize:any' in current_user.get_permissions()
    if not (note.rounding_physician_id == current_user.id or can_finalize_any):
        return jsonify({"error": "Unauthorized to finalize this note (not author or no 'any' privilege)."}), 403

    note.is_finalized = True
    note.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"message": "RoundingNote finalized", "rounding_note": note.to_dict()})

@rounds_bp.route('/rounding-notes/<string:note_id>/review', methods=['POST'])
@permission_required('rounding_note:review')
def review_rounding_note(note_id):
    current_user = g.current_user
    note = RoundingNote.query.get_or_404(note_id)
    data = request.json or {} # Ensure data is a dict

    if not note.is_finalized:
        return jsonify({"error": "Cannot review a note that is not finalized."}), 400
    # Allow re-review or only one review? For now, allow re-review by updating fields.
    # if note.reviewed_at:
    #     return jsonify({"message": "RoundingNote already reviewed."}), 400

    if note.rounding_physician_id == current_user.id:
        return jsonify({"error": "Cannot review your own rounding note."}), 403

    note.reviewed_by_id = current_user.id
    note.reviewed_at = datetime.utcnow()
    note.review_notes = data.get('review_notes', note.review_notes) # Allow updating review notes
    note.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"message": "RoundingNote reviewed", "rounding_note": note.to_dict()})

@rounds_bp.route('/all-rounding-notes', methods=['GET'])
@permission_required('rounding_note:read:any')
def list_all_rounding_notes_admin():
    # Filters similar to list_rounding_notes_for_patient can be applied here
    patient_id_filter = request.args.get('patient_id')
    physician_id_filter = request.args.get('rounding_physician_id')
    # ... other filters ...

    query = RoundingNote.query
    if patient_id_filter: query = query.filter_by(patient_id=patient_id_filter)
    if physician_id_filter: query = query.filter_by(rounding_physician_id=physician_id_filter)
    # ... apply other filters ...

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    notes_pagination = query.order_by(RoundingNote.rounding_datetime.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        "rounding_notes": [note.to_dict() for note in notes_pagination.items],
        "total": notes_pagination.total, "page": notes_pagination.page,
        "per_page": notes_pagination.per_page, "pages": notes_pagination.pages
    }), 200
