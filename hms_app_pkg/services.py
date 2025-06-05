# hms_app_pkg/services.py
# This file will contain internal helper/service functions used across different blueprints.

import uuid
import datetime
from flask import current_app
from . import db  # Imports db from hms_app_pkg/__init__.py
from .models import Notification, User, Patient # Import all necessary models
from sqlalchemy import and_

# --- Notification Services ---

def create_notification( # Renamed for clarity as a service function
    recipient_user_ids,
    message_template,
    template_context=None,
    notification_type="GENERAL",
    link_to_item_type=None,
    link_to_item_id=None,
    related_patient_id=None, # Make sure Patient model is imported if using this
    is_urgent=False,
    metadata_json=None,
    cooldown_minutes=5
):
    """
    Creates one or more notifications.
    This function is intended to be called internally by other application services or routes.
    """
    if isinstance(recipient_user_ids, int):
        recipient_user_ids = [recipient_user_ids]
    elif not isinstance(recipient_user_ids, list):
        current_app.logger.error(f"[NotificationService] recipient_user_ids must be an int or a list of ints. Got: {type(recipient_user_ids)}")
        return None

    sent_notifications_data = [] # To return dicts instead of model objects
    if not recipient_user_ids:
        return []

    notifications_to_add = []

    for user_id in recipient_user_ids:
        user = User.query.get(user_id)
        if not user:
            current_app.logger.warning(f"[NotificationService] Skipping notification for non-existent user_id: {user_id}")
            continue

        try:
            message = message_template.format(**(template_context or {}))
        except KeyError as e:
            current_app.logger.error(f"[NotificationService] Template formatting error for user {user_id}: {e} - Template: '{message_template}', Context: {template_context}")
            continue
        except Exception as e:
            current_app.logger.error(f"[NotificationService] Unexpected error formatting message for user {user_id}: {e}")
            continue

        if cooldown_minutes > 0:
            cooldown_threshold = datetime.datetime.utcnow() - datetime.timedelta(minutes=cooldown_minutes)
            recent_duplicate = Notification.query.filter(
                Notification.recipient_user_id == user_id,
                Notification.notification_type == notification_type,
                Notification.message == message,
                Notification.link_to_item_type == link_to_item_type,
                Notification.link_to_item_id == link_to_item_id,
                Notification.created_at >= cooldown_threshold
            ).first()

            if recent_duplicate:
                current_app.logger.info(f"[NotificationService] Cooldown: Skipped duplicate for user {user_id}, type '{notification_type}'.")
                continue
        
        # Validate related_patient_id if provided
        if related_patient_id and not Patient.query.get(related_patient_id):
            current_app.logger.warning(f"[NotificationService] related_patient_id '{related_patient_id}' not found. Proceeding without it for notification to user {user_id}.")
            related_patient_id = None # Clear it if invalid

        try:
            notification = Notification(
                recipient_user_id=user_id,
                message=message,
                notification_type=notification_type,
                link_to_item_type=link_to_item_type,
                link_to_item_id=link_to_item_id,
                related_patient_id=related_patient_id,
                is_urgent=is_urgent,
                metadata_json=metadata_json
            )
            notifications_to_add.append(notification)
        except Exception as e:
            current_app.logger.error(f"[NotificationService] Failed to instantiate Notification object for user {user_id}: {e}")
            continue

    if not notifications_to_add:
        return []

    try:
        db.session.add_all(notifications_to_add)
        db.session.commit()
        for n in notifications_to_add: # Convert to dict after successful commit (so IDs are populated)
            sent_notifications_data.append(n.to_dict())
            current_app.logger.info(f"[NotificationService] Created: ID {n.id} for User {n.recipient_user_id}, Type '{n.notification_type}'")
        # Here you could also trigger real-time push notifications
        return sent_notifications_data
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[NotificationService] Database commit failed while saving notifications: {e}")
        return None

# --- Other Internal Service Functions for other modules can be added below ---
# Example:
# def process_new_order_for_pharmacy(order_id):
#     # ... logic ...
#     pass
# --- Order Services (example stub) ---

def notify_order_signature_required(order_id, signing_user_id, patient_id, order_display_str):
    """
    Notify a user that an order requires their signature.
    Intended to be called when an order is created/submitted and needs cosignature.
    """
    return create_notification(
        recipient_user_ids=signing_user_id,
        message_template="Order '{order_desc}' for patient requires your signature.",
        template_context={"order_desc": order_display_str},
        notification_type="ORDER_SIGNATURE_REQUESTED",
        link_to_item_type="Order",
        link_to_item_id=order_id,
        related_patient_id=patient_id,
        is_urgent=True,
        cooldown_minutes=0  # Let these through always
    )


# --- Lab Result Services (example stub) ---

def notify_critical_lab_result(lab_result_id, patient_id, lab_display_str, care_team_user_ids):
    """
    Notifies care team of a critical lab result.
    Typically triggered when lab result marked as 'critical'.
    """
    return create_notification(
        recipient_user_ids=care_team_user_ids,
        message_template="Critical lab alert: {lab_info}",
        template_context={"lab_info": lab_display_str},
        notification_type="CRITICAL_LAB",
        link_to_item_type="LabResult",
        link_to_item_id=lab_result_id,
        related_patient_id=patient_id,
        is_urgent=True,
        cooldown_minutes=10
    )


# --- Task Assignment Services (example stub) ---

def notify_task_assignment(task_id, assignee_user_id, task_title, patient_id=None):
    """
    Notify user of a newly assigned task.
    """
    return create_notification(
        recipient_user_ids=assignee_user_id,
        message_template="New task assigned: {task_title}",
        template_context={"task_title": task_title},
        notification_type="TASK_ASSIGNED",
        link_to_item_type="Task",
        link_to_item_id=task_id,
        related_patient_id=patient_id,
        is_urgent=False,
        cooldown_minutes=5
    )
def process_new_order_for_pharmacy(order_id):
    """
    Triggered when a new medication order is placed and needs to be reviewed by pharmacy.
    Sends a notification to pharmacy staff or group.

    Parameters:
        order_id (str): UUID of the new order.
    """
    from .models import Order, UserGroup  # Assuming these models exist

    # Step 1: Fetch order
    order = Order.query.get(order_id)
    if not order:
        current_app.logger.warning(f"[PharmacyOrderService] Order {order_id} not found.")
        return None

    # Step 2: Determine pharmacy recipients (could be user group or fixed role)
    pharmacy_group = UserGroup.query.filter_by(name="Pharmacy").first()
    if not pharmacy_group or not pharmacy_group.members:
        current_app.logger.error("[PharmacyOrderService] No pharmacy recipients found.")
        return None

    pharmacy_user_ids = [u.id for u in pharmacy_group.members]

    # Step 3: Format message
    medication_name = order.medication_name if hasattr(order, "medication_name") else "Medication"
    patient = order.patient  # assuming a relationship exists

    return create_notification(
        recipient_user_ids=pharmacy_user_ids,
        message_template="New medication order for {patient_name}: {medication_name}",
        template_context={
            "patient_name": f"{patient.first_name} {patient.last_name}" if patient else "Unknown Patient",
            "medication_name": medication_name
        },
        notification_type="NEW_ORDER_PHARMACY",
        link_to_item_type="Order",
        link_to_item_id=order.id,
        related_patient_id=order.patient_id,
        is_urgent=True,
        cooldown_minutes=3  # Avoid spamming
    )
