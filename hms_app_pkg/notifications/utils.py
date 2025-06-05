# hms_app_pkg/notifications/utils.py
import uuid
import datetime
from flask import current_app
from .. import db # Assuming db is initialized in hms_app_pkg/__init__.py
from ..models import Notification, User # Assuming User model is in hms_app_pkg/models.py
from sqlalchemy import and_ # For the cooldown query

def create_internal_notification(
    recipient_user_ids,
    message_template,
    template_context=None,
    notification_type="GENERAL",
    link_to_item_type=None,
    link_to_item_id=None,
    related_patient_id=None,
    is_urgent=False,
    metadata_json=None,
    cooldown_minutes=5  # Avoid sending the same notification too often for the same user, type, and message
):
    """
    Creates one or more notifications based on provided user(s).
    - Supports template-based messages using `message_template` and `template_context`.
    - Avoids sending duplicate notifications (same user, type, message) within `cooldown_minutes`.
    
    Returns:
        list: A list of successfully created Notification objects, or None if a commit error occurs.
              Returns an empty list if no new notifications were prepared (e.g., all recipients invalid or all duplicates).
    """
    if isinstance(recipient_user_ids, int):
        recipient_user_ids = [recipient_user_ids]
    elif not isinstance(recipient_user_ids, list):
        current_app.logger.error(f"[Notification] recipient_user_ids must be an int or a list of ints. Got: {type(recipient_user_ids)}")
        return None # Or raise an error

    sent_notifications = []
    if not recipient_user_ids:
        return []

    for user_id in recipient_user_ids:
        user = User.query.get(user_id)
        if not user:
            current_app.logger.warning(f"[Notification] Skipping notification for non-existent user_id: {user_id}")
            continue

        # Prepare message with dynamic substitution
        try:
            message = message_template.format(**(template_context or {}))
        except KeyError as e:
            current_app.logger.error(f"[Notification] Template formatting error for user {user_id}: {e} - Template: '{message_template}', Context: {template_context}")
            continue # Skip this user if message can't be formatted
        except Exception as e:
            current_app.logger.error(f"[Notification] Unexpected error formatting message for user {user_id}: {e}")
            continue


        # Check for recent duplicate only if cooldown_minutes is positive
        if cooldown_minutes > 0:
            cooldown_threshold = datetime.datetime.utcnow() - datetime.timedelta(minutes=cooldown_minutes)
            recent_duplicate = Notification.query.filter(
                Notification.recipient_user_id == user_id,
                Notification.notification_type == notification_type,
                Notification.message == message, # Exact message match for cooldown
                Notification.link_to_item_type == link_to_item_type, # Consider link in uniqueness
                Notification.link_to_item_id == link_to_item_id,   # Consider link in uniqueness
                Notification.created_at >= cooldown_threshold
            ).first()

            if recent_duplicate:
                current_app.logger.info(f"[Notification] Cooldown: Skipped duplicate for user {user_id}, type '{notification_type}', item '{link_to_item_type}:{link_to_item_id}'.")
                continue

        try:
            notification = Notification(
                # id is defaulted by model
                recipient_user_id=user_id,
                message=message,
                notification_type=notification_type,
                link_to_item_type=link_to_item_type,
                link_to_item_id=link_to_item_id,
                related_patient_id=related_patient_id,
                is_urgent=is_urgent,
                metadata_json=metadata_json, # Model handles default if this is None and field is nullable
                # created_at is defaulted by model
            )
            db.session.add(notification) # Add to session, commit will happen once after loop
            sent_notifications.append(notification)
        except Exception as e: 
            current_app.logger.error(f"[Notification] Failed to instantiate Notification object for user {user_id}: {e}")
            # No rollback needed here, only on commit failure
            continue # Skip this notification

    if not sent_notifications:
        current_app.logger.info("[Notification] No new notifications were prepared to be sent (all recipients invalid or all duplicates within cooldown).")
        return []

    try:
        db.session.commit() # Commit all prepared notifications at once
        for n in sent_notifications: # Log after successful commit
            current_app.logger.info(f"[Notification] Created: ID {n.id}, User {n.recipient_user_id}, Type '{n.notification_type}', Urgent: {n.is_urgent}, Msg: '{n.message[:50]}...'")
        # Here you could also trigger real-time push notifications (e.g., WebSockets, FCM)
        # for each notification in sent_notifications.
        return sent_notifications
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[Notification] Database commit failed while saving notifications: {e}")
        return None # Indicate a failure to commit
