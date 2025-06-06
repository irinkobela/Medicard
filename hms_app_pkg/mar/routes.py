# hms_app_pkg/mar/routes.py
from flask import Blueprint, request, jsonify, g
from .. import db
from ..models import Patient, PatientMedication, MedicationAdministration
from ..utils import permission_required
from datetime import datetime

mar_bp = Blueprint('mar_bp', __name__)

@mar_bp.route('/mar/administrations', methods=['POST'])
@permission_required('mar:document_administration')
def document_administration():
    """
    Endpoint for a user (e.g., a nurse) to document a medication administration.
    """
    data = request.get_json()
    required_fields = ['patient_medication_id', 'status']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "patient_medication_id and status are required."}), 400

    med_record = PatientMedication.query.get_or_404(data['patient_medication_id'])

    # Create the administration record
    new_admin = MedicationAdministration(
        patient_id=med_record.patient_id,
        patient_medication_id=med_record.id,
        administered_by_user_id=g.current_user.id,
        status=data['status'], # e.g., 'Given', 'Held', 'Patient Refused'
        dose_given=data.get('dose_given', med_record.dose), # Default to prescribed dose
        notes=data.get('notes')
    )

    db.session.add(new_admin)
    db.session.commit()

    return jsonify({
        "message": "Medication administration documented successfully.",
        "administration_record": new_admin.to_dict()
    }), 201


@mar_bp.route('/patients/<string:patient_id>/mar', methods=['GET'])
@permission_required('mar:read')
def get_patient_mar(patient_id):
    """
    Retrieves the complete Medication Administration Record for a patient.
    """
    Patient.query.get_or_404(patient_id) # Ensure patient exists

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Query all administration events for the patient, newest first
    mar_query = MedicationAdministration.query.filter_by(
        patient_id=patient_id
    ).order_by(MedicationAdministration.administration_time.desc())
    
    mar_pagination = mar_query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "mar_records": [rec.to_dict() for rec in mar_pagination.items],
        "total": mar_pagination.total,
        "page": mar_pagination.page,
        "per_page": mar_pagination.per_page,
        "pages": mar_pagination.pages
    })