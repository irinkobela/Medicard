# hms_app_pkg/medications/routes.py
from flask import Blueprint, request, jsonify, current_app, g # Import g
from .. import db
from ..models import Patient, PatientMedication, OrderableItem, MedicationReconciliationLog, User # Ensure User is imported for authorization checks
from ..utils import permission_required # decode_access_token is used by permission_required in utils.py
from datetime import datetime
from sqlalchemy.exc import IntegrityError

medications_bp = Blueprint('medications_bp', __name__)

# The local helper function get_user_id_from_token_for_meds() is removed.
# We will use g.current_user set by the permission_required decorator from utils.py.

@medications_bp.route('/patients/<string:patient_id>/medications', methods=['GET'])
@permission_required('medication:read')
def get_patient_medications(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    # current_user = g.current_user # Available if needed for further authorization
    
    med_type_filter = request.args.get('type')
    status_filter = request.args.get('status', 'Active') # Default to 'Active'

    query = PatientMedication.query.filter_by(patient_id=patient.id)
    if med_type_filter:
        query = query.filter(PatientMedication.type.ilike(f'%{med_type_filter}%'))
    if status_filter and status_filter.lower() != 'all':
        query = query.filter(PatientMedication.status.ilike(f'%{status_filter}%'))
    
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
    current_user = g.current_user # User recording the home medication

    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json()
    if not data: return jsonify({"message": "No data provided"}), 400

    required_fields = ['medication_name', 'dose', 'route', 'frequency']
    if not all(field in data for field in required_fields):
        return jsonify({"message": f"Missing required fields: {', '.join(required_fields)}"}), 400

    last_taken_dt = None
    if data.get('last_taken_datetime'):
        try:
            dt_str = data['last_taken_datetime']
            if not isinstance(dt_str, str): raise ValueError("Datetime must be string")
            last_taken_dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return jsonify({"message": "Invalid last_taken_datetime format. Use ISO format."}), 400
    
    start_dt = datetime.utcnow() # Default if not provided
    if data.get('start_datetime'):
        try:
            dt_str = data['start_datetime']
            if not isinstance(dt_str, str): raise ValueError("Datetime must be string")
            start_dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return jsonify({"message": "Invalid start_datetime format. Use ISO format."}), 400

    try:
        new_home_med = PatientMedication(
            patient_id=patient.id,
            medication_name=data['medication_name'],
            orderable_item_id=data.get('orderable_item_id'),
            type='HOME_MED',
            dose=data['dose'],
            route=data['route'],
            frequency=data['frequency'],
            prn_reason=data.get('prn_reason'),
            indication=data.get('indication'),
            start_datetime=start_dt,
            status='Active',
            source_of_information=data.get('source_of_information', 'Patient'),
            last_taken_datetime=last_taken_dt,
            recorded_by_user_id=current_user.id
        )
        db.session.add(new_home_med)
        db.session.commit()
        return jsonify({"message": "Home medication added successfully", "medication": new_home_med.to_dict()}), 201
    except IntegrityError:
        db.session.rollback()
        current_app.logger.error("IntegrityError adding home medication.")
        return jsonify({"message": "Database integrity error. Check foreign keys or unique constraints."}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error saving home medication: {e}")
        return jsonify({"message": "Error saving home medication", "error": str(e)}), 500


@medications_bp.route('/medications/<string:med_id>', methods=['PUT'])
@permission_required('medication:update') # General update permission
def update_patient_medication(med_id):
    current_user = g.current_user
    medication = PatientMedication.query.get_or_404(med_id)
    data = request.get_json()
    if not data: return jsonify({"message": "No update data provided"}), 400

    # More granular authorization: only original recorder or someone with 'medication:update:any'
    can_update_any = 'medication:update:any' in current_user.get_permissions() # Define this permission if needed
    if medication.recorded_by_user_id != current_user.id and not can_update_any:
        return jsonify({"error": "Unauthorized to update this medication record."}), 403

    # Updateable fields
    if 'medication_name' in data: medication.medication_name = data['medication_name']
    if 'dose' in data: medication.dose = data['dose']
    if 'route' in data: medication.route = data['route']
    if 'frequency' in data: medication.frequency = data['frequency']
    if 'indication' in data: medication.indication = data['indication']
    if 'status' in data: medication.status = data['status']
    if 'prn_reason' in data: medication.prn_reason = data['prn_reason']
    if 'source_of_information' in data and medication.type == 'HOME_MED':
        medication.source_of_information = data['source_of_information']
    
    # Date fields
    for date_field_name in ['start_datetime', 'end_datetime', 'last_taken_datetime']:
        if date_field_name in data:
            if data[date_field_name] is None:
                setattr(medication, date_field_name, None)
            else:
                try:
                    dt_str = data[date_field_name]
                    if not isinstance(dt_str, str): raise ValueError("Date must be string")
                    setattr(medication, date_field_name, datetime.fromisoformat(dt_str.replace('Z', '+00:00')))
                except (ValueError, TypeError):
                    return jsonify({"error": f"Invalid {date_field_name} format. Use ISO format or null."}), 400
            
    try:
        medication.updated_at = datetime.utcnow() # Assuming your PatientMedication model has updated_at
        db.session.commit()
        return jsonify({"message": "Medication record updated", "medication": medication.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating medication {med_id}: {e}")
        return jsonify({"message": "Error updating medication record."}), 500


@medications_bp.route('/patients/<string:patient_id>/medications/reconcile', methods=['POST'])
@permission_required('medication:reconcile')
def reconcile_medications(patient_id):
    current_user = g.current_user
    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json()

    reconciliation_type = data.get('reconciliation_type')
    decisions_log_payload = data.get('decisions_log')

    if not reconciliation_type or not isinstance(decisions_log_payload, list):
        return jsonify({"message": "reconciliation_type (string) and decisions_log (array) are required."}), 400

    # Placeholder for complex logic of processing decisions_log.
    # This would involve creating/updating PatientMedication records.
    current_app.logger.info(f"Medication reconciliation process initiated by user {current_user.id} for patient {patient_id}, type: {reconciliation_type}.")
    current_app.logger.info(f"Decisions payload: {decisions_log_payload}")


    new_log = MedicationReconciliationLog(
        patient_id=patient.id,
        reconciliation_type=reconciliation_type,
        reconciled_by_user_id=current_user.id,
        decisions_log=decisions_log_payload,
        notes=data.get('notes')
    )
    try:
        db.session.add(new_log)
        db.session.commit()
        return jsonify({"message": f"{reconciliation_type} reconciliation logged successfully. Further processing of decisions pending.", "log_id": new_log.id}), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error logging medication reconciliation for patient {patient_id}: {e}")
        return jsonify({"message": "Error logging medication reconciliation."}), 500

@medications_bp.route('/patients/<string:patient_id>/medications/reconciliation-logs', methods=['GET'])
@permission_required('medication:reconcile:read_log')
def get_reconciliation_logs(patient_id):
    Patient.query.get_or_404(patient_id) # Ensure patient exists
    # Add authorization for who can see these logs
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    logs_pagination = MedicationReconciliationLog.query.filter_by(patient_id=patient_id).order_by(MedicationReconciliationLog.reconciliation_datetime.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        "reconciliation_logs": [log.to_dict() for log in logs_pagination.items],
        "total": logs_pagination.total,
        "page": logs_pagination.page,
        "per_page": logs_pagination.per_page,
        "pages": logs_pagination.pages
    }), 200
