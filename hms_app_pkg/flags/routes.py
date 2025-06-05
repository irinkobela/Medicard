# hms_app_pkg/flags/routes.py
from flask import Blueprint, request, jsonify, current_app, g # Import g
from .. import db
from ..models import PatientFlag, Patient, User
from ..utils import permission_required # decode_access_token is used by permission_required
from datetime import datetime
from sqlalchemy.exc import IntegrityError
# import uuid # Not strictly needed as model defaults ID

flags_bp = Blueprint('flags_bp', __name__)

# The local get_user_id_from_token_for_flags() helper is removed.
# We will use g.current_user set by the permission_required decorator from utils.py.

@flags_bp.route('/patients/<string:patient_id>/flags', methods=['POST'])
@permission_required('flag:create')
def create_flag_for_patient(patient_id):
    current_user = g.current_user # User creating the flag

    patient = Patient.query.get_or_404(patient_id) # Ensures patient exists

    data = request.get_json()
    if not data or not data.get('flag_type'):
        return jsonify({"message": "flag_type is required."}), 400

    expires_at_val = None
    if data.get('expires_at'):
        try:
            expires_at_val = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
        except (ValueError, TypeError): # Catch TypeError if data['expires_at'] is not a string
            return jsonify({"message": "Invalid expires_at format. Use ISO format or null."}), 400

    try:
        new_flag = PatientFlag(
            patient_id=patient_id,
            flagged_by_user_id=current_user.id,
            flag_type=data['flag_type'],
            severity=data.get('severity'),
            notes=data.get('notes'),
            expires_at=expires_at_val,
            is_active=data.get('is_active', True) # Default to active if not specified
        )
        db.session.add(new_flag)
        db.session.commit()
        return jsonify({'message': 'Flag created successfully', 'flag': new_flag.to_dict()}), 201
    except IntegrityError:
        db.session.rollback()
        current_app.logger.error("IntegrityError creating patient flag.")
        return jsonify({"error": "Database integrity error creating flag."}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating patient flag: {e}")
        return jsonify({"error": "Could not create patient flag."}), 500


@flags_bp.route('/flags/<string:flag_id>', methods=['GET'])
@permission_required('flag:read')
def get_flag(flag_id):
    flag = PatientFlag.query.get_or_404(flag_id)
    current_user = g.current_user
    
    # Authorization check: Can the current user view this flag?
    # (e.g., if it's for a patient they can access, or they have 'flag:read:any')
    can_read_any = 'flag:read:any' in current_user.get_permissions()
    # A more detailed check might involve checking if current_user has access to flag.patient_id
    # For now, if not 'flag:read:any', we assume the base 'flag:read' might imply access to flags
    # related to their patients, but this would need more specific logic if 'flag:read' is too broad.
    # If 'flag:read' is meant to be 'flag:read:own' (created by self), then:
    # if not (flag.flagged_by_user_id == current_user.id or can_read_any):
    #     return jsonify({"error": "Unauthorized to view this flag."}), 403
        
    return jsonify(flag.to_dict())

@flags_bp.route('/patients/<string:patient_id>/flags', methods=['GET'])
@permission_required('flag:read')
def list_flags_for_patient(patient_id):
    Patient.query.get_or_404(patient_id) # Ensure patient exists
    current_user = g.current_user
    # Add similar authorization as in get_flag if needed to restrict access to this patient's flags

    active_only_str = request.args.get('active_only', 'true', type=str)
    active_only = active_only_str.lower() == 'true'

    flag_type_filter = request.args.get('flag_type')
    severity_filter = request.args.get('severity')

    query = PatientFlag.query.filter_by(patient_id=patient_id)
    if active_only:
        query = query.filter_by(is_active=True)
    if flag_type_filter:
        query = query.filter(PatientFlag.flag_type.ilike(f'%{flag_type_filter}%'))
    if severity_filter:
        query = query.filter(PatientFlag.severity.ilike(f'%{severity_filter}%'))
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    flags_pagination = query.order_by(PatientFlag.is_active.desc(), PatientFlag.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "flags": [f.to_dict() for f in flags_pagination.items],
        "total": flags_pagination.total,
        "page": flags_pagination.page,
        "per_page": flags_pagination.per_page,
        "pages": flags_pagination.pages
    }), 200

@flags_bp.route('/flags/<string:flag_id>', methods=['PUT'])
@permission_required('flag:update') # Or 'flag:update:own' for more granular control
def update_flag(flag_id):
    current_user = g.current_user
    flag = PatientFlag.query.get_or_404(flag_id)
    
    can_update_any = 'flag:update:any' in current_user.get_permissions()
    if not (flag.flagged_by_user_id == current_user.id or can_update_any):
        return jsonify({"error": "Unauthorized to update this flag."}), 403

    data = request.get_json()
    if not data: return jsonify({"error": "No update data provided."}), 400

    flag.flag_type = data.get('flag_type', flag.flag_type)
    flag.severity = data.get('severity', flag.severity)
    flag.notes = data.get('notes', flag.notes)
    if 'expires_at' in data:
        if data['expires_at'] is None:
            flag.expires_at = None
        else:
            try:
                flag.expires_at = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
            except (ValueError, TypeError):
                return jsonify({"message": "Invalid expires_at format for update."}), 400
    
    if 'is_active' in data and isinstance(data['is_active'], bool):
        flag.is_active = data['is_active']
        if not flag.is_active and not flag.reviewed_at: # Optionally mark reviewed when deactivated
             flag.reviewed_at = datetime.utcnow()
             flag.reviewed_by_user_id = current_user.id
             flag.review_notes = data.get('deactivation_reason', "Deactivated during update.")


    flag.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'Flag updated successfully', 'flag': flag.to_dict()})

@flags_bp.route('/flags/<string:flag_id>/review', methods=['POST'])
@permission_required('flag:review')
def review_flag(flag_id):
    current_user = g.current_user
    flag = PatientFlag.query.get_or_404(flag_id)

    # Allow re-review by the same or different person; new review overrides old.
    # if flag.reviewed_at:
    #     return jsonify({"message": "Flag already reviewed."}), 400

    if flag.flagged_by_user_id == current_user.id and not 'flag:review:own' in current_user.get_permissions(): # Own flag review needs explicit permission
        return jsonify({"error": "Cannot review a flag you created without specific permission."}), 403

    data = request.get_json()
    review_notes_text = data.get('review_notes') if data else "Reviewed." # Default review note

    flag.mark_reviewed(reviewer_id=current_user.id, notes=review_notes_text) # Uses model method
    db.session.commit()
    return jsonify({'message': 'Flag reviewed successfully', 'flag': flag.to_dict()})

@flags_bp.route('/flags/<string:flag_id>/deactivate', methods=['POST'])
@permission_required('flag:deactivate') # More specific than general update
def deactivate_flag(flag_id):
    current_user = g.current_user
    flag = PatientFlag.query.get_or_404(flag_id)

    can_deactivate_any = 'flag:deactivate:any' in current_user.get_permissions()
    if not (flag.flagged_by_user_id == current_user.id or can_deactivate_any):
        return jsonify({"error": "Unauthorized to deactivate this flag."}), 403

    if not flag.is_active:
        return jsonify({"message": "Flag is already inactive."}), 400
        
    data = request.get_json()
    deactivation_reason = data.get('deactivation_reason', "Deactivated.") if data else "Deactivated."
    
    flag.deactivate() # Uses model method
    # If deactivation implies review or needs a note for deactivation itself
    if not flag.reviewed_at : # Mark reviewed upon deactivation if not already
        flag.mark_reviewed(reviewer_id=current_user.id, notes=deactivation_reason)
    else: # If already reviewed, just update review notes if provided
        flag.review_notes = f"{flag.review_notes or ''} Deactivated: {deactivation_reason}".strip()


    db.session.commit()
    return jsonify({'message': 'Flag deactivated successfully', 'flag': flag.to_dict()})
