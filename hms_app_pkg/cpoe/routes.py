# Upgraded hms_app_pkg/cpoe/routes.py
from flask import Blueprint, request, jsonify, current_app, g
from .. import db
from ..models import Patient, Order, OrderableItem, User, PatientAllergy
from ..utils import permission_required
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
from datetime import datetime

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
    item = OrderableItem.query.get(data['orderable_item_id'])
    if not item:
        return jsonify({"message": "Orderable item not found"}), 404

    alerts = []

    existing = Order.query.filter_by(patient_id=patient.id, orderable_item_id=item.id, status='Active').first()
    if existing:
        alerts.append({
            "type": "DUPLICATE_ORDER",
            "message": f"An active order for '{item.name}' already exists (Order ID: {existing.id}).",
            "severity": "Warning"
        })

    if item.item_type == 'Medication':
        for allergy in PatientAllergy.query.filter_by(patient_id=patient.id, is_active=True):
            if item.name.lower() in allergy.allergen_name.lower() or \
               (item.generic_name and item.generic_name.lower() in allergy.allergen_name.lower()):
                alerts.append({
                    "type": "ALLERGY_ALERT",
                    "message": f"Patient allergic to '{allergy.allergen_name}' — may react to '{item.name}'. Severity: {allergy.severity}.",
                    "severity": "Critical"
                })
                break

    if any(alert['severity'] == 'Critical' for alert in alerts):
        return jsonify({"message": "Order blocked by critical CDS alert(s).", "cds_alerts": alerts}), 400

    order = Order(
        patient_id=patient.id,
        orderable_item_id=item.id,
        order_details=data['order_details'],
        priority=data.get('priority', 'Routine'),
        status='PendingSignature',
        ordering_physician_id=user.id
    )

    try:
        db.session.add(order)
        db.session.commit()
        response = {
            "message": "Order created successfully and is pending signature.",
            "order_id": order.id
        }
        if alerts:
            response["cds_warnings"] = alerts
        return jsonify(response), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "Database integrity error creating order."}), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating order: {e}")
        return jsonify({"message": "Unexpected error while creating order."}), 500

@cpoe_bp.route('/patients/<string:patient_id>/orders', methods=['GET'])
@permission_required('order:read')
def get_patient_orders(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    status = request.args.get('status')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = Order.query.options(joinedload(Order.item), joinedload(Order.ordering_physician)).filter_by(patient_id=patient.id)
    if status:
        query = query.filter(Order.status.ilike(f'%{status}%'))

    pagination = query.order_by(Order.order_placed_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    orders = [{
        "order_id": o.id,
        "orderable_item_id": o.orderable_item_id,
        "orderable_item_name": o.item.name if o.item else "Unknown",
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

    try:
        db.session.commit()
        return jsonify({"message": "Order signed successfully.", "order_id": order.id, "status": order.status}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Signing error for order {order_id}: {e}")
        return jsonify({"message": "Error signing order."}), 500

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

    try:
        db.session.commit()
        return jsonify({"message": "Order discontinued.", "order_id": order.id}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Discontinue error for order {order_id}: {e}")
        return jsonify({"message": "Error discontinuing order."}), 500