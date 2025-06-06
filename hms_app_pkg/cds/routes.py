# hms_app_pkg/cds/routes.py
from flask import Blueprint, request, jsonify, g
from .services import execute_cds_checks
from ..models import Patient, OrderableItem
from ..utils import permission_required

cds_bp = Blueprint('cds_bp', __name__)

@cds_bp.route('/cds/execute-checks', methods=['POST'])
@permission_required('cds:execute') # We'll add this permission
def execute_checks_route():
    """
    An endpoint to run CDS checks for a potential order.
    This is called by the frontend or other services before placing an order.
    """
    data = request.get_json()
    patient_id = data.get('patient_id')
    orderable_item_id = data.get('orderable_item_id')
    order_details = data.get('order_details', {})

    if not all([patient_id, orderable_item_id]):
        return jsonify({"error": "patient_id and orderable_item_id are required."}), 400

    patient = Patient.query.get_or_404(patient_id)
    order_item = OrderableItem.query.get_or_404(orderable_item_id)

    # Call our main service function to get all alerts
    alerts = execute_cds_checks(patient, order_item, order_details)

    return jsonify({"cds_alerts": alerts}), 200