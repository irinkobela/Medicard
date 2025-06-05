# hms_app_pkg/medications/routes.py
from flask import Blueprint, request, jsonify, current_app
from .. import db
from ..models import Patient, PatientMedication, OrderableItem, MedicationReconciliationLog, User
from ..utils import permission_required, decode_access_token # Using our existing utils
from datetime import datetime # Python's datetime
from sqlalchemy.exc import IntegrityError

medications_bp = Blueprint('medications_bp', __name__) # Consistent naming

# Helper to get user ID (should be centralized in utils.py)
def get_user_id_from_token_for_meds():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None, jsonify({"message": "Authorization token is missing or badly formatted."}), 401
    token = auth_header.split(" ")[1]
    payload = decode_access_token(token)
    if isinstance(payload, str): return None, jsonify({"message": payload}), 401
    user_id_str = payload.get('sub')
    if not user_id_str: return None, jsonify({"message": "User ID (sub) missing in token."}), 401
    try:
        return int(user_id_str), None, None
    except ValueError:
        current_app.logger.error(f"Could not convert sub claim '{user_id_str}' to int.")
        return None, jsonify({"message": "Invalid user ID format in token."}), 401

@medications_bp.route('/patients/<string:patient_id>/medications', methods=['GET'])
@permission_required('medication:read')
def get_patient_medications(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    med_type_filter = request.args.get('type')  # e.g., 'INPATIENT_ACTIVE', 'HOME_MED', 'DISCHARGE_MED'
    status_filter = request.args.get('status', 'Active') # Default to active, allow 'All' or specific status

    query = PatientMedication.query.filter_by(patient_id=patient.id)
    if med_type_filter:
        query = query.filter(PatientMedication.type.ilike(f'%{med_type_filter}%'))
    if status_filter and status_filter.lower() != 'all':
        query = query.filter(PatientMedication.status.ilike(f'%{status_filter}%'))
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    meds_pagination = query.order_by(PatientMedication.start_datetime.desc()).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "medications": [m.to_dict() for m in meds_pagination.items],
        "total": meds_pagination.total,
        "page": meds_pagination.page,
        "per_page": meds_pagination.per_page,
        "pages": meds_pagination.pages
    }), 200

@medications_bp.route('/patients/<string:patient_id>/medications/home', methods=['POST'])
@permission_required('medication:manage_home_meds')
def add_home_medication(patient_id):
    user_id_recording, error_response, status_code = get_user_id_from_token_for_meds()
    if error_response:
        return error_response, status_code

    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json()
    if not data: return jsonify({"message": "No data provided"}), 400

    required_fields = ['medication_name', 'dose', 'route', 'frequency']
    if not all(field in data for field in required_fields):
        return jsonify({"message": f"Missing required fields: {', '.join(required_fields)}"}), 400

    last_taken_dt = None
    if data.get('last_taken_datetime'):
        try:
            last_taken_dt = datetime.fromisoformat(data['last_taken_datetime'].replace('Z', '+00:00'))
        except ValueError:
            return jsonify({"message": "Invalid last_taken_datetime format. Use ISO format."}), 400
    
    start_dt = datetime.utcnow() # Default for home med, or can be passed
    if data.get('start_datetime'):
        try:
            start_dt = datetime.fromisoformat(data['start_datetime'].replace('Z', '+00:00'))
        except ValueError:
            return jsonify({"message": "Invalid start_datetime format. Use ISO format."}), 400


    new_home_med = PatientMedication(
        patient_id=patient.id,
        medication_name=data['medication_name'],
        orderable_item_id=data.get('orderable_item_id'), # Optional: if it matches a formulary item
        type='HOME_MED',
        dose=data['dose'],
        route=data['route'],
        frequency=data['frequency'],
        prn_reason=data.get('prn_reason'),
        indication=data.get('indication'),
        start_datetime=start_dt,
        status='Active', # Home meds are active until reconciled
        source_of_information=data.get('source_of_information', 'Patient'),
        last_taken_datetime=last_taken_dt,
        recorded_by_user_id=user_id_recording
    )
    try:
        db.session.add(new_home_med)
        db.session.commit()
        return jsonify({"message": "Home medication added successfully", "medication": new_home_med.to_dict()}), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "Database integrity error. Check if medication already exists or foreign keys are valid."}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error saving home medication: {e}")
        return jsonify({"message": "Error saving home medication", "error": str(e)}), 500


@medications_bp.route('/medications/<string:med_id>', methods=['PUT'])
@permission_required('medication:update') # General update permission
def update_patient_medication(med_id):
    user_id_updating, error_response, status_code = get_user_id_from_token_for_meds()
    if error_response: return error_response, status_code

    medication = PatientMedication.query.get_or_404(med_id)
    data = request.get_json()
    if not data: return jsonify({"message": "No update data provided"}), 400

    # Authorization: e.g., only creator or user with 'medication:update:any' can update.
    # if medication.recorded_by_user_id != user_id_updating and not User.query.get(user_id_updating).has_permission('medication:update:any'):
    #     return jsonify({"error": "Unauthorized to update this medication record."}), 403

    # Updateable fields
    if 'medication_name' in data: medication.medication_name = data['medication_name']
    if 'dose' in data: medication.dose = data['dose']
    if 'route' in data: medication.route = data['route']
    if 'frequency' in data: medication.frequency = data['frequency']
    if 'indication' in data: medication.indication = data['indication']
    if 'status' in data: medication.status = data['status'] # e.g., 'Discontinued', 'Held'
    if 'prn_reason' in data: medication.prn_reason = data['prn_reason']
    if 'source_of_information' in data and medication.type == 'HOME_MED': medication.source_of_information = data['source_of_information']
    
    if 'start_datetime' in data and data['start_datetime']:
        try: medication.start_datetime = datetime.fromisoformat(data['start_datetime'].replace('Z', '+00:00'))
        except ValueError: return jsonify({"error": "Invalid start_datetime format."}), 400
    if 'end_datetime' in data: # Can be null
        if data['end_datetime'] is None: medication.end_datetime = None
        else:
            try: medication.end_datetime = datetime.fromisoformat(data['end_datetime'].replace('Z', '+00:00'))
            except ValueError: return jsonify({"error": "Invalid end_datetime format."}), 400
    if 'last_taken_datetime' in data and medication.type == 'HOME_MED':
        if data['last_taken_datetime'] is None: medication.last_taken_datetime = None
        else:
            try: medication.last_taken_datetime = datetime.fromisoformat(data['last_taken_datetime'].replace('Z', '+00:00'))
            except ValueError: return jsonify({"error": "Invalid last_taken_datetime format."}), 400
            
    try:
        db.session.commit()
        return jsonify({"message": "Medication record updated", "medication": medication.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating medication {med_id}: {e}")
        return jsonify({"message": "Error updating medication record."}), 500


@medications_bp.route('/patients/<string:patient_id>/medications/reconcile', methods=['POST'])
@permission_required('medication:reconcile')
def reconcile_medications(patient_id):
    user_id_reconciling, error_response, status_code = get_user_id_from_token_for_meds()
    if error_response:
        return error_response, status_code

    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json()

    reconciliation_type = data.get('reconciliation_type') # ADMISSION, TRANSFER, DISCHARGE
    decisions_log_payload = data.get('decisions_log') # Expects array of decision objects

    if not reconciliation_type or not isinstance(decisions_log_payload, list):
        return jsonify({"message": "reconciliation_type (string) and decisions_log (array) are required."}), 400

    # Complex logic for processing decisions_log:
    # For each item in decisions_log_payload:
    #   - If action is 'CONTINUE_HOME_MED_AS_INPATIENT', create new INPATIENT_ACTIVE PatientMedication from home med.
    #   - If action is 'DISCONTINUE_HOME_MED', update status of existing HOME_MED PatientMedication.
    #   - If action is 'START_NEW_INPATIENT', create new INPATIENT_ACTIVE PatientMedication.
    #   - If action is 'CONVERT_INPATIENT_TO_DISCHARGE', create DISCHARGE_MED PatientMedication.
    # This logic needs careful implementation based on exact workflow.
    # For now, we just log the raw decisions.

    new_log = MedicationReconciliationLog(
        patient_id=patient.id,
        reconciliation_type=reconciliation_type,
        reconciled_by_user_id=user_id_reconciling,
        decisions_log=decisions_log_payload, # Storing the provided decisions
        notes=data.get('notes')
    )
    try:
        db.session.add(new_log)
        db.session.commit()
        # Potentially trigger other actions based on reconciliation type and decisions
        return jsonify({"message": f"{reconciliation_type} reconciliation logged successfully", "log_id": new_log.id}), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error logging medication reconciliation: {e}")
        return jsonify({"message": "Error logging medication reconciliation."}), 500

@medications_bp.route('/patients/<string:patient_id>/medications/reconciliation-logs', methods=['GET'])
@permission_required('medication:reconcile:read_log') # New permission
def get_reconciliation_logs(patient_id):
    Patient.query.get_or_404(patient_id)
    logs = MedicationReconciliationLog.query.filter_by(patient_id=patient_id).order_by(MedicationReconciliationLog.reconciliation_datetime.desc()).all()
    return jsonify([log.to_dict() for log in logs]), 200

