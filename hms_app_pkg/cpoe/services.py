# hms_app_pkg/cpoe/services.py
from ..models import Order, OrderableItem, Patient, User, PatientAllergy
from .. import db
from ..cds.services import execute_cds_checks

def create_new_order(patient: Patient, user: User, order_data: dict):
    """
    Service to handle the business logic of creating a new order.
    Returns a tuple of (new_order, alerts, error_message, status_code).
    """
    orderable_item_id = order_data.get('orderable_item_id')

    item = OrderableItem.query.get(orderable_item_id)
    if not item:
        return None, None, "Orderable item not found", 404

    alerts = []

    # 1. Check for duplicate active orders
    existing = Order.query.filter_by(
        patient_id=patient.id,
        orderable_item_id=item.id,
        status='Active'
    ).first()
    if existing:
        alerts.append({
            "type": "DUPLICATE_ORDER",
            "message": f"An active order for '{item.name}' already exists (Order ID: {existing.id}).",
            "severity": "Warning"
        })

    # 2. Check for allergies (Clinical Decision Support Check)
    if item.item_type == 'Medication':
        for allergy in PatientAllergy.query.filter_by(patient_id=patient.id, is_active=True):
            if item.name.lower() in allergy.allergen_name.lower() or \
               (item.generic_name and item.generic_name.lower() in allergy.allergen_name.lower()):
                alerts.append({
                    "type": "ALLERGY_ALERT",
                    "message": f"Patient has a documented allergy to '{allergy.allergen_name}', which may be related to '{item.name}'.",
                    "severity": "Critical"
                })
                break # Found a critical allergy, no need to check further

    # 3. Block order if there are any critical alerts
    if any(alert['severity'] == 'Critical' for alert in alerts):
        return None, alerts, "Order blocked by critical CDS alert(s).", 400

    # 4. If no critical alerts, prepare the new order object
    order = Order(
        patient_id=patient.id,
        orderable_item_id=item.id,
        order_details=order_data.get('order_details'),
        priority=order_data.get('priority', 'Routine'),
        status='PendingSignature',  # Orders should always start as pending signature
        ordering_physician_id=user.id
    )
def create_new_order(patient: Patient, user: User, order_data: dict):
    """
    Service to handle the business logic of creating a new order.
    This now includes running CDS checks.
    Returns a tuple of (new_order, alerts, error_message, status_code).
    """
    orderable_item_id = order_data.get('orderable_item_id')

    item = OrderableItem.query.get(orderable_item_id)
    if not item:
        return None, None, "Orderable item not found", 404

    # --- UPGRADE: Execute all CDS checks from our new engine ---
    alerts = execute_cds_checks(patient, item, order_data)

    # Block order if there are any critical alerts
    if any(alert['severity'] == 'Critical' for alert in alerts):
        return None, alerts, "Order blocked by critical CDS alert(s).", 400

    # If no critical alerts, prepare the new order object
    order = Order(
        patient_id=patient.id,
        orderable_item_id=item.id,
        order_details=order_data.get('order_details'),
        priority=order_data.get('priority', 'Routine'),
        status='PendingSignature',
        ordering_physician_id=user.id
    )

    db.session.add(order)

    # Return the order and any non-critical (warning) alerts
    return order, alerts, None, None
