# hms_app_pkg/handoff/routes.py
from flask import Blueprint, request, jsonify, current_app, g # Import g
from .. import db
from ..models import HandoffEntry, Patient, User # PatientAllergy might be needed if auto-populating allergies
from ..utils import permission_required # decode_access_token is used by permission_required in utils.py
from datetime import datetime
from sqlalchemy.exc import IntegrityError

handoff_bp = Blueprint('handoff_bp', __name__)

# The local get_user_id_from_token_for_handoff() helper is removed.
# We will use g.current_user set by the permission_required decorator from utils.py.

@handoff_bp.route('/patients/<string:patient_id>/handoff-entries', methods=['POST'])
@permission_required('handoff:create')
def create_handoff_entry(patient_id):
    # g.current_user is set by the permission_required decorator
    user_writing = g.current_user 

    patient_for_snapshot = Patient.query.get_or_404(patient_id) # Ensures patient exists

    data = request.json # Use request.json for consistency, it handles content type
    if not data or not all(key in data for key in ['current_condition', 'active_issues', 'plan_for_next_shift']):
        return jsonify({"error": "Missing required fields: current_condition, active_issues, plan_for_next_shift"}), 400
    
    # Auto-populate snapshot data if not provided in payload, or use payload's version
    allergies_snapshot = data.get('allergies_summary_at_handoff')
    if allergies_snapshot is None: # If not provided, try to generate it
        allergies_list = [a.allergen_name for a in patient_for_snapshot.allergies if a.is_active]
        allergies_snapshot = ", ".join(allergies_list) if allergies_list else "NKA"
        
    code_status_snapshot = data.get('code_status_at_handoff', patient_for_snapshot.code_status)
    isolation_snapshot = data.get('isolation_precautions_at_handoff', patient_for_snapshot.isolation_precautions)

    try:
        entry = HandoffEntry(
            patient_id=patient_id,
            written_by_user_id=user_writing.id,
            current_condition=data.get('current_condition'),
            active_issues=data.get('active_issues'),
            overnight_events=data.get('overnight_events'),
            anticipatory_guidance=data.get('anticipatory_guidance'),
            plan_for_next_shift=data.get('plan_for_next_shift'),
            vital_signs_summary=data.get('vital_signs_summary'),
            medications_changes_summary=data.get('medications_changes_summary'),
            labs_pending_summary=data.get('labs_pending_summary'),
            consults_pending_summary=data.get('consults_pending_summary'),
            allergies_summary_at_handoff=allergies_snapshot,
            code_status_at_handoff=code_status_snapshot,
            isolation_precautions_at_handoff=isolation_snapshot,
            handoff_priority=data.get('handoff_priority', 'Normal')
        )
        db.session.add(entry)
        db.session.commit()
        return jsonify(entry.to_dict()), 201
    except IntegrityError:
        db.session.rollback()
        current_app.logger.error("IntegrityError creating handoff entry.")
        return jsonify({"error": "Database integrity error."}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating handoff entry: {e}")
        return jsonify({"error": "Could not create handoff entry."}), 500


@handoff_bp.route('/handoff-entries/<string:entry_id>', methods=['GET'])
@permission_required('handoff:read')
def get_handoff_entry(entry_id):
    entry = HandoffEntry.query.get_or_404(entry_id)
    current_user = g.current_user
    
    # Authorization: Can current_user view this handoff?
    # Example: if it's for a patient they have access to, or they are part of the handoff.
    # Or if they have 'handoff:read:any'. This logic can be enhanced.
    can_read_any = 'handoff:read:any' in current_user.get_permissions()
    if not (entry.written_by_user_id == current_user.id or \
            (entry.reviewed_by_user_id and entry.reviewed_by_user_id == current_user.id) or \
            can_read_any):
        # Add more sophisticated patient access check if needed
        # For instance, check if current_user is attending for entry.patient_id
        # if not is_user_on_patient_care_team(current_user.id, entry.patient_id):
        return jsonify({"error": "Unauthorized to view this handoff entry."}), 403
            
    return jsonify(entry.to_dict())

@handoff_bp.route('/patients/<string:patient_id>/handoff-entries', methods=['GET'])
@permission_required('handoff:read')
def list_handoff_entries_for_patient(patient_id):
    Patient.query.get_or_404(patient_id) # Ensure patient exists
    current_user = g.current_user

    # Authorization: Can user view handoffs for THIS patient?
    # Needs a function like: can_user_access_patient_data(current_user.id, patient_id)
    # or check if 'handoff:read:any' is present.
    # For now, the @permission_required('handoff:read') is a base check.

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    query = HandoffEntry.query.filter_by(patient_id=patient_id)

    if start_date_str:
        try:
            query = query.filter(HandoffEntry.written_at >= datetime.fromisoformat(start_date_str.replace('Z', '+00:00')))
        except ValueError: return jsonify({"error": "Invalid start_date format"}), 400
    if end_date_str:
        try:
            query = query.filter(HandoffEntry.written_at <= datetime.fromisoformat(end_date_str.replace('Z', '+00:00')))
        except ValueError: return jsonify({"error": "Invalid end_date format"}), 400

    entries_pagination = query.order_by(HandoffEntry.written_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        "handoff_entries": [e.to_dict() for e in entries_pagination.items],
        "total": entries_pagination.total,
        "page": entries_pagination.page,
        "per_page": entries_pagination.per_page,
        "pages": entries_pagination.pages
    }), 200


@handoff_bp.route('/handoff-entries/<string:entry_id>', methods=['PUT'])
@permission_required('handoff:update') # Or 'handoff:update:own'
def update_handoff_entry(entry_id):
    current_user = g.current_user
    entry = HandoffEntry.query.get_or_404(entry_id)
    
    can_update_any = 'handoff:update:any' in current_user.get_permissions()
    can_update_reviewed = 'handoff:update:reviewed' in current_user.get_permissions()

    if not (entry.written_by_user_id == current_user.id or can_update_any):
        return jsonify({"error": "Unauthorized: You are not the author or lack general update privileges."}), 403
    
    if entry.reviewed_at and not (can_update_reviewed or can_update_any):
        return jsonify({"error": "Cannot update an already reviewed handoff entry without specific privileges."}), 403

    data = request.json
    if not data: return jsonify({"error": "No update data provided"}), 400
    
    updatable_fields = [
        'current_condition', 'active_issues', 'overnight_events',
        'anticipatory_guidance', 'plan_for_next_shift', 'vital_signs_summary',
        'medications_changes_summary', 'labs_pending_summary', 'consults_pending_summary',
        'allergies_summary_at_handoff', 'code_status_at_handoff', 
        'isolation_precautions_at_handoff', 'handoff_priority', 'review_notes'
    ]
    for field in updatable_fields:
        if field in data: # Only update fields present in the request
            setattr(entry, field, data[field])
    
    entry.last_updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"message": "HandoffEntry updated", "handoff_entry": entry.to_dict()})

@handoff_bp.route('/handoff-entries/<string:entry_id>/review', methods=['POST'])
@permission_required('handoff:review')
def review_handoff_entry(entry_id):
    current_user = g.current_user
    entry = HandoffEntry.query.get_or_404(entry_id)

    if entry.reviewed_at and entry.reviewed_by_user_id == current_user.id: # If already reviewed by this user
        return jsonify({"message": "You have already reviewed this handoff entry."}), 400
    if entry.reviewed_at and entry.reviewed_by_user_id != current_user.id:
         return jsonify({"message": "Handoff entry already reviewed by another user."}), 400


    if entry.written_by_user_id == current_user.id:
        return jsonify({"error": "Cannot review your own handoff entry."}), 403

    data = request.json
    review_notes_text = data.get('review_notes') if data else None

    entry.mark_reviewed(reviewer_id=current_user.id, notes=review_notes_text) # Model method handles setting reviewed_at
    db.session.commit()
    return jsonify({"message": "HandoffEntry reviewed", "handoff_entry": entry.to_dict()})


@handoff_bp.route('/handoff-entries/<string:entry_id>', methods=['DELETE'])
@permission_required('handoff:delete') # Or 'handoff:delete:own'
def delete_handoff_entry(entry_id):
    current_user = g.current_user
    entry = HandoffEntry.query.get_or_404(entry_id)

    can_delete_any = 'handoff:delete:any' in current_user.get_permissions()

    if not (entry.written_by_user_id == current_user.id or can_delete_any):
        return jsonify({"error": "Unauthorized to delete this handoff entry."}), 403

    db.session.delete(entry)
    db.session.commit()
    return jsonify({"message": "HandoffEntry deleted"}), 200
