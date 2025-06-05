# hms_app_pkg/vitalsigns/routes.py
from flask import Blueprint, request, jsonify, current_app, g # Import g
from .. import db
from ..models import VitalSign, Patient, User # Ensure all are imported
from ..utils import permission_required # decode_access_token is used by permission_required
from sqlalchemy.exc import IntegrityError
from datetime import datetime, date, timedelta # Python's datetime
import math # For pow if needed by any direct calculations (not used here now)

# Ensure this matches the blueprint variable name used in hms_app_pkg/__init__.py
vitalsigns_bp = Blueprint('vitalsigns_bp', __name__) # If your folder is 'vitalsigns', this is fine.

# The local helper function get_user_id_from_token_for_vitals() is removed.
# We will use g.current_user set by the permission_required decorator from utils.py.

# The calculate_bmi_util and calculate_news2_util functions are removed,
# as these calculations are now @property methods in the VitalSign model
# and will be included in vital.to_dict().

@vitalsigns_bp.route('/patients/<string:patient_id>/vitals', methods=['POST'])
@permission_required('vitals:record')
def create_vital(patient_id):
    current_user = g.current_user # User performing the action

    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json()
    if not data:
        return jsonify({"message": "No data provided."}), 400

    recorded_at_val = datetime.utcnow() # Default to now
    if data.get('recorded_at'):
        try:
            recorded_at_str = data['recorded_at']
            if not isinstance(recorded_at_str, str): raise ValueError("Datetime must be string")
            if '.' in recorded_at_str:
                recorded_at_val = datetime.strptime(recorded_at_str, '%Y-%m-%dT%H:%M:%S.%f')
            else:
                recorded_at_val = datetime.strptime(recorded_at_str, '%Y-%m-%dT%H:%M:%S')
        except (ValueError, TypeError):
            return jsonify({"message": "Invalid recorded_at format. Use ISO format (YYYY-MM-DDTHH:MM:SS or YYYY-MM-DDTHH:MM:SS.ffffff)."}), 400

    def get_numeric(key, data_type=float): # Local helper for this route
        val = data.get(key)
        if val is not None: # Allow explicit null to clear a value if model supports nullable
            try: return data_type(val) if val is not None else None
            except (ValueError, TypeError): return None # Or raise an error if strict parsing is required
        return None # If key not in data

    try:
        new_vitals = VitalSign(
            patient_id=patient.id,
            recorded_by_user_id=current_user.id,
            recorded_at=recorded_at_val,
            temperature_celsius=get_numeric('temperature_celsius'),
            heart_rate_bpm=get_numeric('heart_rate_bpm', int),
            respiratory_rate_rpm=get_numeric('respiratory_rate_rpm', int),
            systolic_bp_mmhg=get_numeric('systolic_bp_mmhg', int),
            diastolic_bp_mmhg=get_numeric('diastolic_bp_mmhg', int),
            oxygen_saturation_percent=get_numeric('oxygen_saturation_percent'),
            pain_score_0_10=get_numeric('pain_score_0_10', int),
            weight_kg=get_numeric('weight_kg'),
            height_cm=get_numeric('height_cm'),
            blood_glucose_mg_dl=get_numeric('blood_glucose_mg_dl', int),
            blood_glucose_mmol_l=get_numeric('blood_glucose_mmol_l'),
            blood_glucose_type=data.get('blood_glucose_type'),
            consciousness_level=data.get('consciousness_level'),
            patient_position=data.get('patient_position'),
            activity_level=data.get('activity_level'),
            o2_therapy_device=data.get('o2_therapy_device'),
            o2_flow_rate_lpm=get_numeric('o2_flow_rate_lpm'),
            fio2_percent=get_numeric('fio2_percent'),
            troponin_ng_l=get_numeric('troponin_ng_l'),
            creatinine_umol_l=get_numeric('creatinine_umol_l'),
            ecg_changes=data.get('ecg_changes'),
            # The specific history fields (known_cad, hypertension, etc.) are on the Patient model
            # and will be used by the @property scores in VitalSign model via self.patient.
            notes=data.get('notes')
        )
        db.session.add(new_vitals)
        db.session.commit()
        return jsonify(new_vitals.to_dict()), 201 # to_dict() will include calculated scores
    except IntegrityError as e:
        db.session.rollback()
        current_app.logger.error(f"Integrity error creating vital: {e}")
        return jsonify({"message": "Error saving vital signs. Check data integrity (e.g., patient_id, user_id).", "error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unexpected error creating vital: {e}")
        return jsonify({"message": "An unexpected error occurred while saving vital signs."}), 500


@vitalsigns_bp.route('/patients/<string:patient_id>/vitals', methods=['GET'])
@permission_required('vitals:read')
def get_all_vitals_for_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    # current_user = g.current_user # Available for more granular authorization if needed

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 30, type=int)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    query = VitalSign.query.filter_by(patient_id=patient.id)
    if start_date_str:
        try:
            start_dt = datetime.fromisoformat(start_date_str.replace('Z', '+00:00'))
            query = query.filter(VitalSign.recorded_at >= start_dt)
        except (ValueError, TypeError): return jsonify({"message": "Invalid start_date format. Use ISO format."}), 400
    if end_date_str:
        try:
            end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
            # To include the whole end day, adjust end_dt if only date part is given
            # if end_dt.hour == 0 and end_dt.minute == 0 and end_dt.second == 0:
            #    end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            query = query.filter(VitalSign.recorded_at <= end_dt)
        except (ValueError, TypeError): return jsonify({"message": "Invalid end_date format. Use ISO format."}), 400

    vitals_pagination = query.order_by(VitalSign.recorded_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        "vitals": [v.to_dict() for v in vitals_pagination.items], # to_dict() includes calculated scores
        "total": vitals_pagination.total, "page": vitals_pagination.page,
        "per_page": vitals_pagination.per_page, "pages": vitals_pagination.pages
    }), 200

@vitalsigns_bp.route('/vitals/<string:vital_id>', methods=['GET'])
@permission_required('vitals:read')
def get_vital(vital_id):
    vital = VitalSign.query.get_or_404(vital_id)
    # current_user = g.current_user # Available for more granular authorization
    # Add authorization logic: Can current_user view vitals for vital.patient_id?
    return jsonify(vital.to_dict()) # to_dict() includes calculated scores

@vitalsigns_bp.route('/vitals/<string:vital_id>', methods=['PUT'])
@permission_required('vitals:update')
def update_vital(vital_id):
    current_user = g.current_user
    vital = VitalSign.query.get_or_404(vital_id)

    can_update_any = 'vitals:update:any' in current_user.get_permissions()
    if not (vital.recorded_by_user_id == current_user.id or can_update_any): # Basic auth check
        return jsonify({"message": "Unauthorized to update this vital signs entry."}), 403
    
    data = request.get_json()
    if not data: return jsonify({"message": "No update data provided."}), 400

    def get_numeric(key, data_type=float): # Local helper for this route
        val = data.get(key)
        if val is not None:
            try: return data_type(val) if val is not None else None
            except (ValueError, TypeError): return vital.__getattribute__(key) # Keep old if invalid, or None if strict
        return vital.__getattribute__(key) # Keep old if key not in data

    if 'recorded_at' in data and data.get('recorded_at'):
        try:
            rec_at_str = data['recorded_at']
            if not isinstance(rec_at_str, str): raise ValueError("Datetime must be string")
            vital.recorded_at = datetime.fromisoformat(rec_at_str.replace('Z', '+00:00'))
        except (ValueError, TypeError): return jsonify({"message": "Invalid recorded_at format."}), 400
    
    # Explicitly list fields that can be updated
    for field_name in ['temperature_celsius', 'oxygen_saturation_percent', 'weight_kg', 'height_cm',
                       'blood_glucose_mmol_l', 'o2_flow_rate_lpm', 'fio2_percent', 
                       'troponin_ng_l', 'creatinine_umol_l']:
        if field_name in data:
            setattr(vital, field_name, get_numeric(field_name))
            
    for field_name_int in ['heart_rate_bpm', 'respiratory_rate_rpm', 'systolic_bp_mmhg', 
                           'diastolic_bp_mmhg', 'pain_score_0_10', 'blood_glucose_mg_dl']:
        if field_name_int in data:
            setattr(vital, field_name_int, get_numeric(field_name_int, int))

    for field_name_str in ['blood_glucose_type', 'consciousness_level', 'patient_position', 
                           'activity_level', 'o2_therapy_device', 'ecg_changes', 'notes']:
        if field_name_str in data:
            setattr(vital, field_name_str, data.get(field_name_str))
            
    try:
        vital.updated_at = datetime.utcnow() # Assuming VitalSign model has an updated_at field
        db.session.commit()
        return jsonify(vital.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating vital {vital_id}: {e}")
        return jsonify({"message": "Error updating vital signs."}), 500

@vitalsigns_bp.route('/vitals/<string:vital_id>', methods=['DELETE'])
@permission_required('vitals:delete')
def delete_vital(vital_id):
    current_user = g.current_user
    vital = VitalSign.query.get_or_404(vital_id)

    can_delete_any = 'vitals:delete:any' in current_user.get_permissions()
    if not (vital.recorded_by_user_id == current_user.id or can_delete_any):
        return jsonify({"message": "Unauthorized to delete this vital signs entry."}), 403

    try:
        db.session.delete(vital)
        db.session.commit()
        return '', 204 # No content for successful delete
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting vital {vital_id}: {e}")
        return jsonify({"message": "Error deleting vital signs entry."}), 500

# The /derived-scores/latest endpoint is now effectively covered by
# GET /patients/<patient_id>/vitals/latest if the model's to_dict() includes scores.
# If you still want it for a specific vital_id, it would be:
@vitalsigns_bp.route('/vitals/<string:vital_id>/derived-scores', methods=['GET'])
@permission_required('vitals:read:derived_scores')
def get_derived_scores_for_specific_vitals(vital_id):
    vital = VitalSign.query.get_or_404(vital_id)
    # The to_dict() method will include the @property scores.
    return jsonify(vital.to_dict()), 200

@vitalsigns_bp.route('/patients/<string:patient_id>/vitals/latest', methods=['GET'])
@permission_required('vitals:read')
def get_latest_vital_signs(patient_id): # This was already good
    patient = Patient.query.get_or_404(patient_id)
    latest_vitals = VitalSign.query.filter_by(patient_id=patient.id).order_by(VitalSign.recorded_at.desc()).first()
    
    if not latest_vitals:
        return jsonify({"message": "No vital signs recorded for this patient."}), 404
        
    return jsonify(latest_vitals.to_dict()), 200
