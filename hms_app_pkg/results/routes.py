# hms_app_pkg/results/routes.py
from flask import Blueprint, request, jsonify, current_app, g
from .. import db
from ..models import Patient, LabResult, ImagingReport, User
from ..utils import permission_required
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from ..services import create_notification

results_bp = Blueprint('results_bp', __name__)


@results_bp.route('/patients/<string:patient_id>/results/labs', methods=['GET'])
@permission_required('result:read:lab')
def get_lab_results(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    # current_user = g.current_user # Available for more granular auth if needed

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    test_name_filter = request.args.get('test_name')
    status_filter = request.args.get('status')

    query = LabResult.query.filter_by(patient_id=patient.id)
    if test_name_filter:
        query = query.filter(LabResult.test_name.ilike(f'%{test_name_filter}%'))
    if status_filter:
        query = query.filter(LabResult.status.ilike(f'%{status_filter}%'))
        
    results_pagination = query.order_by(LabResult.result_datetime.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        "lab_results": [res.to_dict() for res in results_pagination.items],
        "total": results_pagination.total,
        "page": results_pagination.page,
        "per_page": results_pagination.per_page,
        "pages": results_pagination.pages
    }), 200
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
        if not isinstance(collection_dt_str, str): raise ValueError("Datetime must be a string.")
        if '.' in collection_dt_str:
            collection_dt = datetime.strptime(collection_dt_str, '%Y-%m-%dT%H:%M:%S.%f')
        else:
            collection_dt = datetime.strptime(collection_dt_str, '%Y-%m-%dT%H:%M:%S')
    except (ValueError, TypeError) as e:
        current_app.logger.error(f"Invalid collection_datetime format: {data.get('collection_datetime')}, Error: {e}")
        return jsonify({"message": "Invalid collection_datetime format. Use ISO format."}), 400

    value_numeric = None
    if 'value' in data:
        try:
            if isinstance(data['value'], (int, float)) or \
               (isinstance(data['value'], str) and data['value'].replace('.', '', 1).replace('-', '', 1).isdigit()):
                value_numeric = float(data['value'])
        except (ValueError, TypeError):
            pass

    try:
        new_result = LabResult(
            patient_id=patient.id,
            test_name=data['test_name'],
            panel_name=data.get('panel_name'),
            value=str(data['value']),
            value_numeric=value_numeric,
            units=data.get('units'),
            reference_range=data.get('reference_range'),
            abnormal_flag=data.get('abnormal_flag'),
            status=data.get('status', 'Final'),
            collection_datetime=collection_dt,
            result_datetime=datetime.utcnow()
        )
        db.session.add(new_result)
        db.session.commit() # Commit to get the new_result.id

        # --- NOTIFICATION TRIGGER LOGIC ---
        # Check if the result is critical and there's an attending physician to notify.
        if new_result.abnormal_flag and 'CRITICAL' in new_result.abnormal_flag.upper() and patient.attending_physician_id:
            attending_physician_id = patient.attending_physician_id
            patient_name = f"{patient.first_name} {patient.last_name}"

            # Call the notification service
            create_notification(
                recipient_user_ids=attending_physician_id,
                message_template="Critical Lab for {patient_name}: {test_name} is {value} {units}.",
                template_context={
                    "patient_name": patient_name,
                    "test_name": new_result.test_name,
                    "value": new_result.value,
                    "units": new_result.units
                },
                notification_type="CRITICAL_LAB_RESULT",
                link_to_item_type="LabResult", # For frontend navigation
                link_to_item_id=new_result.id,
                related_patient_id=patient.id,
                is_urgent=True
            )
        # --- END NOTIFICATION TRIGGER ---
        
        return jsonify({"message": "Lab result created successfully", "result": new_result.to_dict()}), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "Database integrity error creating lab result."}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unexpected error creating lab result: {e}")
        return jsonify({"message": "An unexpected error occurred."}), 500

# --- Imaging Reports Routes ---
@results_bp.route('/patients/<string:patient_id>/results/imaging', methods=['POST'])
@permission_required('result:create:imaging')
def create_imaging_report(patient_id):
    # current_user = g.current_user # Available if needed
    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json()
    required_fields = ['modality', 'study_description', 'study_datetime', 'report_text']
    if not all(field in data for field in required_fields):
        return jsonify({"message": "Missing required fields: " + ", ".join(required_fields)}), 400
    try:
        study_dt_str = data['study_datetime']
        if not isinstance(study_dt_str, str): raise ValueError("Datetime must be string.")
        if '.' in study_dt_str:
            study_dt = datetime.strptime(study_dt_str, '%Y-%m-%dT%H:%M:%S.%f')
        else:
            study_dt = datetime.strptime(study_dt_str, '%Y-%m-%dT%H:%M:%S')
    except (ValueError, TypeError) as e:
        current_app.logger.error(f"Invalid study_datetime format: {data.get('study_datetime')}, Error: {e}")
        return jsonify({"message": "Invalid study_datetime format. Use ISO format."}), 400
    
    try:
        new_report = ImagingReport(
            patient_id=patient.id,
            modality=data['modality'],
            study_description=data['study_description'],
            study_datetime=study_dt,
            report_text=data['report_text'],
            impression_text=data.get('impression_text'),
            status=data.get('status', 'Final'),
            report_datetime=datetime.utcnow()
            # ordered_study_id=data.get('ordered_study_id') # If linking to OrderableItem
            # reported_by_user_id=current_user.id # If user directly creates it, vs. system
        )
        db.session.add(new_report)
        db.session.commit()
        return jsonify({"message": "Imaging report created successfully", "report": new_report.to_dict()}), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "Database integrity error creating imaging report."}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating imaging report: {e}")
        return jsonify({"message": "An unexpected error occurred."}), 500


@results_bp.route('/patients/<string:patient_id>/results/imaging', methods=['GET'])
@permission_required('result:read:imaging')
def get_imaging_reports(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    # current_user = g.current_user # Available for auth checks

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int) # Fewer reports per page
    modality_filter = request.args.get('modality')
    status_filter = request.args.get('status')

    query = ImagingReport.query.filter_by(patient_id=patient.id)
    if modality_filter:
        query = query.filter(ImagingReport.modality.ilike(f'%{modality_filter}%'))
    if status_filter:
        query = query.filter(ImagingReport.status.ilike(f'%{status_filter}%'))

    reports_pagination = query.order_by(ImagingReport.report_datetime.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        "imaging_reports": [rep.to_dict() for rep in reports_pagination.items],
        "total": reports_pagination.total,
        "page": reports_pagination.page,
        "per_page": reports_pagination.per_page,
        "pages": reports_pagination.pages
    }), 200

# --- Result Acknowledgement Endpoints ---
@results_bp.route('/results/labs/<string:result_id>/acknowledge', methods=['POST'])
@permission_required('result:acknowledge:lab')
def acknowledge_lab_result(result_id):
    current_user = g.current_user # User acknowledging the result

    result = LabResult.query.filter_by(id=result_id).first_or_404(
        description="Lab result not found."
    )
    # Add logic to ensure current_user can acknowledge results for result.patient_id
    
    if result.acknowledged_at:
        return jsonify({"message": "Lab result already acknowledged.", "result": result.to_dict()}), 400 # Or 200 if not an error

    result.acknowledged_at = datetime.utcnow()
    result.acknowledged_by_user_id = current_user.id
    try:
        db.session.commit()
        return jsonify({"message": "Lab result acknowledged successfully.", "result": result.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error acknowledging lab result {result_id}: {e}")
        return jsonify({"message": "Error acknowledging lab result."}), 500


@results_bp.route('/results/imaging/<string:report_id>/acknowledge', methods=['POST'])
@permission_required('result:acknowledge:imaging')
def acknowledge_imaging_report(report_id):
    current_user = g.current_user # User acknowledging the report

    report = ImagingReport.query.filter_by(id=report_id).first_or_404(
        description="Imaging report not found."
    )
    # Add logic to ensure current_user can acknowledge reports for report.patient_id

    if report.acknowledged_at:
        return jsonify({"message": "Imaging report already acknowledged.", "report": report.to_dict()}), 400 # Or 200

    report.acknowledged_at = datetime.utcnow()
    report.acknowledged_by_user_id = current_user.id
    try:
        db.session.commit()
        return jsonify({"message": "Imaging report acknowledged successfully.", "report": report.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error acknowledging imaging report {report_id}: {e}")
        return jsonify({"message": "Error acknowledging imaging report."}), 500
