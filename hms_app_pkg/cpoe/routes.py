# Upgraded hms_app_pkg/cpoe/routes.py
from flask import Blueprint, request, jsonify, current_app, g
from .. import db
from ..models import Patient, Order, OrderableItem, User, PatientAllergy
from ..utils import permission_required
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
from datetime import datetime

# --- NEW: Import the service function ---
from .services import create_new_order

cpoe_bp = Blueprint('cpoe_bp', __name__)

@cpoe_bp.route('/orderable-items', methods=['GET'])
@permission_required('order:read_catalog')
def get_orderable_items():
    query = request.args.get('query', '')
    item_type = request.args.get('type')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    items_query = OrderableItem.query.filter_by(is_active=True)

    if query:
        items_query = items_query.filter(OrderableItem.name.ilike(f'%{query}%'))
    if item_type:
        items_query = items_query.filter(OrderableItem.item_type.ilike(f'%{item_type}%'))

    pagination = items_query.order_by(OrderableItem.name).paginate(page=page, per_page=per_page, error_out=False)

    items = [{
        "id": item.id,
        "name": item.name,
        "type": item.item_type,
        "generic_name": item.generic_name,
        "code": item.code
    } for item in pagination.items]

    return jsonify({
        "orderable_items": items,
        "total": pagination.total,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "pages": pagination.pages
    }), 200

@cpoe_bp.route('/patients/<string:patient_id>/orders', methods=['POST'])
@permission_required('order:create')
def create_order(patient_id):
    user = g.current_user
    data = request.get_json()

    if not data or not all(k in data for k in ['orderable_item_id', 'order_details']):
        return jsonify({"message": "orderable_item_id and order_details are required"}), 400

    patient = Patient.query.get_or_404(patient_id)

    # --- UPDATED: Call the service to handle the logic ---
    order, alerts, error_message, status_code = create_new_order(
        patient=patient, user=user, order_data=data
    )

    if error_message:
        # If the service returned an error (like a critical alert), respond immediately
        response_data = {"message": error_message}
        if alerts:
            response_data["cds_alerts"] = alerts
        return jsonify(response_data), status_code

    # If the service was successful, we can now commit the new order to the database
    try:
        db.session.commit()

        response = {
            "message": "Order created successfully and is pending signature.",
            "order_id": order.id
        }
        if alerts: # Include any non-critical warnings that were generated
            response["cds_warnings"] = alerts
        return jsonify(response), 201

    except IntegrityError:
        db.session.rollback()
        current_app.logger.error(f"IntegrityError on order creation for patient {patient_id}")
        return jsonify({"message": "Database integrity error creating order."}), 500
    # Note: The global handler we created in Step 1 will catch other database errors.


@cpoe_bp.route('/patients/<string:patient_id>/orders', methods=['GET'])
@permission_required('order:read')
def get_patient_orders(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    status = request.args.get('status')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = Order.query.options(joinedload(Order.orderable_item), joinedload(Order.ordering_physician)).filter_by(patient_id=patient.id)
    if status:
        query = query.filter(Order.status.ilike(f'%{status}%'))

    pagination = query.order_by(Order.order_placed_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    orders = [{
        "order_id": o.id,
        "orderable_item_id": o.orderable_item_id,
        "orderable_item_name": o.orderable_item.name if o.orderable_item else "Unknown",
        "order_details": o.order_details,
        "status": o.status,
        "priority": o.priority,
        "ordering_physician_id": o.ordering_physician_id,
        "ordering_physician_name": o.ordering_physician.full_name if o.ordering_physician else None,
        "placed_at": o.order_placed_at.isoformat() if o.order_placed_at else None,
        "signed_at": o.signed_at.isoformat() if o.signed_at else None,
        "signed_by_user_id": o.signed_by_user_id
    } for o in pagination.items]

    return jsonify({
        "orders": orders,
        "total": pagination.total,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "pages": pagination.pages
    }), 200

@cpoe_bp.route('/orders/<string:order_id>/sign', methods=['POST'])
@permission_required('order:sign')
def sign_order(order_id):
    user = g.current_user
    order = Order.query.get_or_404(order_id)

    if order.status != 'PendingSignature':
        return jsonify({"message": "Only orders with status 'PendingSignature' can be signed."}), 400

    order.status = 'Active'
    order.signed_at = datetime.utcnow()
    order.signed_by_user_id = user.id

    db.session.commit()
    return jsonify({"message": "Order signed successfully.", "order_id": order.id, "status": order.status}), 200


@cpoe_bp.route('/orders/<string:order_id>/discontinue', methods=['POST'])
@permission_required('order:discontinue')
def discontinue_order(order_id):
    user = g.current_user
    order = Order.query.get_or_404(order_id)

    if order.status not in ['Active', 'PendingSignature']:
        return jsonify({"message": "Only 'Active' or 'PendingSignature' orders can be discontinued."}), 400

    if order.status == 'Discontinued':
        return jsonify({"message": "Order already discontinued."}), 400

    data = request.get_json()
    reason = data.get('reason') if data else None
    order.status = 'Discontinued'
    order.discontinued_at = datetime.utcnow()
    order.discontinued_by_user_id = user.id
    order.discontinuation_reason = reason or 'Discontinued by physician order.'

    db.session.commit()
    return jsonify({"message": "Order discontinued.", "order_id": order.id}), 200