# hms_app_pkg/results/routes.py
from flask import Blueprint, request, jsonify, current_app
from .. import db
from ..models import Patient, LabResult, ImagingReport, User
from ..utils import permission_required, decode_access_token # Ensure decode_access_token is imported
import datetime

results_bp = Blueprint('results_bp', __name__)

# --- Helper function to get user_id from token ---
def get_user_id_from_token():
    """
    Extracts and validates user_id from the Authorization Bearer token.
    Returns: (user_id, error_response, status_code)
    If successful, user_id is an int, error_response is None, status_code is None.
    If error, user_id is None, error_response is a jsonify-able dict, status_code is an int.
    """
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None, jsonify({"message": "Authorization token is missing or badly formatted."}), 401
    
    token = auth_header.split(" ")[1]
    
    payload = decode_access_token(token) # decode_access_token is from your utils.py
    if isinstance(payload, str): # Indicates an error message was returned by decode_access_token
        return None, jsonify({"message": payload}), 401 # Propagate the error message
    
    user_id_str = payload.get('sub') # 'sub' claim should be a string
    if not user_id_str:
        return None, jsonify({"message": "User ID (sub) missing in token."}), 401
    
    try:
        user_id = int(user_id_str) # Convert 'sub' (which is a string) back to int for database use
        return user_id, None, None
    except ValueError:
        current_app.logger.error(f"Could not convert sub claim '{user_id_str}' to int.")
        return None, jsonify({"message": "Invalid user ID format in token."}), 401


# --- Lab Results Routes ---
@results_bp.route('/patients/<string:patient_id>/results/labs', methods=['POST'])
@permission_required('result:create:lab')
def create_lab_result(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json()

    required_fields = ['test_name', 'value', 'collection_datetime']
    if not all(field in data for field in required_fields):
        return jsonify({"message": "Missing required fields: test_name, value, collection_datetime"}), 400

    try:
        collection_dt_str = data['collection_datetime']
        if '.' in collection_dt_str:
            collection_dt = datetime.datetime.strptime(collection_dt_str, '%Y-%m-%dT%H:%M:%S.%f')
        else:
            collection_dt = datetime.datetime.strptime(collection_dt_str, '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        return jsonify({"message": "Invalid collection_datetime format. Use ISO format (YYYY-MM-DDTHH:MM:SS or YYYY-MM-DDTHH:MM:SS.ffffff)."}), 400

    value_numeric = None
    try:
        if isinstance(data['value'], (int, float)) or \
           (isinstance(data['value'], str) and data['value'].replace('.', '', 1).replace('-', '', 1).isdigit()):
            value_numeric = float(data['value'])
    except (ValueError, TypeError):
        pass

    new_result = LabResult(
        patient_id=patient.id,
        test_name=data['test_name'],
        panel_name=data.get('panel_name'),
        value=str(data['value']), # Ensure value is stored as string
        value_numeric=value_numeric,
        units=data.get('units'),
        reference_range=data.get('reference_range'),
        abnormal_flag=data.get('abnormal_flag'),
        status=data.get('status', 'Final'),
        collection_datetime=collection_dt,
        result_datetime=datetime.datetime.utcnow()
    )
    db.session.add(new_result)
    db.session.commit()
    return jsonify({"message": "Lab result created successfully", "result_id": new_result.id}), 201

@results_bp.route('/patients/<string:patient_id>/results/labs', methods=['GET'])
@permission_required('result:read:lab')
def get_lab_results(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    results_query = LabResult.query.filter_by(patient_id=patient.id)
    test_name_filter = request.args.get('test_name')
    if test_name_filter:
        results_query = results_query.filter(LabResult.test_name.ilike(f'%{test_name_filter}%'))
    results = results_query.order_by(LabResult.result_datetime.desc()).all()
    results_data = [{
        "id": res.id, "test_name": res.test_name, "panel_name": res.panel_name,
        "value": res.value, "value_numeric": res.value_numeric, "units": res.units,
        "reference_range": res.reference_range, "abnormal_flag": res.abnormal_flag, "status": res.status,
        "collection_datetime": res.collection_datetime.isoformat() if res.collection_datetime else None,
        "result_datetime": res.result_datetime.isoformat() if res.result_datetime else None,
        "acknowledged_at": res.acknowledged_at.isoformat() if res.acknowledged_at else None,
        "acknowledged_by_user_id": res.acknowledged_by_user_id
    } for res in results]
    return jsonify(results_data), 200

# --- Imaging Reports Routes ---
@results_bp.route('/patients/<string:patient_id>/results/imaging', methods=['POST'])
@permission_required('result:create:imaging')
def create_imaging_report(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json()
    required_fields = ['modality', 'study_description', 'study_datetime', 'report_text']
    if not all(field in data for field in required_fields):
        return jsonify({"message": "Missing required fields"}), 400
    try:
        study_dt_str = data['study_datetime']
        if '.' in study_dt_str:
            study_dt = datetime.datetime.strptime(study_dt_str, '%Y-%m-%dT%H:%M:%S.%f')
        else:
            study_dt = datetime.datetime.strptime(study_dt_str, '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        return jsonify({"message": "Invalid study_datetime format. Use ISO format."}), 400
    new_report = ImagingReport(
        patient_id=patient.id, modality=data['modality'],
        study_description=data['study_description'], study_datetime=study_dt,
        report_text=data['report_text'], impression_text=data.get('impression_text'),
        status=data.get('status', 'Final'), report_datetime=datetime.datetime.utcnow()
    )
    db.session.add(new_report)
    db.session.commit()
    return jsonify({"message": "Imaging report created successfully", "report_id": new_report.id}), 201

@results_bp.route('/patients/<string:patient_id>/results/imaging', methods=['GET'])
@permission_required('result:read:imaging')
def get_imaging_reports(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    reports = ImagingReport.query.filter_by(patient_id=patient.id).order_by(ImagingReport.report_datetime.desc()).all()
    reports_data = [{
        "id": rep.id, "modality": rep.modality, "study_description": rep.study_description,
        "impression_text": rep.impression_text, "status": rep.status,
        "study_datetime": rep.study_datetime.isoformat() if rep.study_datetime else None,
        "report_datetime": rep.report_datetime.isoformat() if rep.report_datetime else None,
        "acknowledged_at": rep.acknowledged_at.isoformat() if rep.acknowledged_at else None,
        "acknowledged_by_user_id": rep.acknowledged_by_user_id
    } for rep in reports]
    return jsonify(reports_data), 200

# --- Result Acknowledgement Endpoints ---
@results_bp.route('/results/labs/<string:result_id>/acknowledge', methods=['POST'])
@permission_required('result:acknowledge:lab')
def acknowledge_lab_result(result_id):
    user_id, error_response, status_code = get_user_id_from_token()
    if error_response:
        return error_response, status_code

    result = LabResult.query.get_or_404(result_id)
    if result.acknowledged_at:
        return jsonify({"message": "Lab result already acknowledged."}), 400

    result.acknowledged_at = datetime.datetime.utcnow()
    result.acknowledged_by_user_id = user_id # Use user_id from validated token
    db.session.commit()
    return jsonify({"message": "Lab result acknowledged successfully.", "acknowledged_at": result.acknowledged_at.isoformat()}), 200

@results_bp.route('/results/imaging/<string:report_id>/acknowledge', methods=['POST'])
@permission_required('result:acknowledge:imaging')
def acknowledge_imaging_report(report_id):
    user_id, error_response, status_code = get_user_id_from_token()
    if error_response:
        return error_response, status_code

    report = ImagingReport.query.get_or_404(report_id)
    if report.acknowledged_at:
        return jsonify({"message": "Imaging report already acknowledged."}), 400

    report.acknowledged_at = datetime.datetime.utcnow()
    report.acknowledged_by_user_id = user_id # Use user_id from validated token
    db.session.commit()
    return jsonify({"message": "Imaging report acknowledged successfully.", "acknowledged_at": report.acknowledged_at.isoformat()}), 200
