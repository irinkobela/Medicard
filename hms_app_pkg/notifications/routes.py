# hms_app_pkg/notifications/routes.py
from flask import Blueprint, request, jsonify, current_app, g
from .. import db # Corrected: Import db from the parent package __init__
from ..models import Notification, User # Corrected: Import models from parent package
from ..utils import permission_required # Using our centralized decorator
from datetime import datetime
from sqlalchemy import or_ # For potential future use in complex queries

notifications_bp = Blueprint('notifications_bp', __name__) # Consistent blueprint naming

# All routes assume g.current_user is set by the permission_required decorator from utils.py

@notifications_bp.route('/notifications', methods=['GET'])
@permission_required('notification:read') # User must be able to read their own notifications
def get_notifications():
    """Get paginated list of notifications for the current user."""
    current_user = g.current_user

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    # Optional filters
    is_read_filter_str = request.args.get('is_read')  # 'true' / 'false'
    notification_type_filter = request.args.get('type')  # e.g. CRITICAL_LAB
    is_urgent_str = request.args.get('is_urgent')  # 'true' / 'false'

    query = Notification.query.filter_by(recipient_user_id=current_user.id)

    if is_read_filter_str is not None:
        is_read_filter = is_read_filter_str.lower() == 'true'
        query = query.filter_by(is_read=is_read_filter)

    if notification_type_filter:
        query = query.filter(Notification.notification_type.ilike(f'%{notification_type_filter}%'))

    if is_urgent_str is not None:
        is_urgent_filter = is_urgent_str.lower() == 'true'
        query = query.filter_by(is_urgent=is_urgent_filter)

    query = query.order_by(Notification.created_at.desc())
    notifications_pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "notifications": [n.to_dict() for n in notifications_pagination.items],
        "total": notifications_pagination.total,
        "unread_count": Notification.query.filter_by(
            recipient_user_id=current_user.id, is_read=False
        ).count(),
        "page": notifications_pagination.page,
        "per_page": notifications_pagination.per_page,
        "pages": notifications_pagination.pages
    }), 200

@notifications_bp.route('/notifications/<string:notification_id>/mark-read', methods=['POST'])
@permission_required('notification:update') # Permission to update (mark as read) own notifications
def mark_notification_as_read(notification_id):
    """Mark a single notification as read."""
    current_user = g.current_user

    notification = Notification.query.filter_by(
        id=notification_id,
        recipient_user_id=current_user.id # Ensure user can only mark their own notifications
    ).first_or_404(description="Notification not found or you do not have access to modify it.")

    if notification.is_read:
        return jsonify({
            "message": "Notification already marked as read.",
            "notification": notification.to_dict()
        }), 200 # Or 400 if considered an error to re-mark

    notification.is_read = True
    notification.read_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "message": "Notification marked as read.",
        "notification": notification.to_dict()
    }), 200

@notifications_bp.route('/notifications/mark-all-read', methods=['POST'])
@permission_required('notification:update') # Permission to update own notifications
def mark_all_notifications_as_read():
    """Mark all unread notifications for the current user as read."""
    current_user = g.current_user

    unread_notifications_query = Notification.query.filter_by(
        recipient_user_id=current_user.id, is_read=False
    )
    
    count = unread_notifications_query.count()
    if count == 0:
        return jsonify({"message": "No unread notifications to mark as read."}), 200

    # Efficiently update all matching notifications
    unread_notifications_query.update({
        Notification.is_read: True,
        Notification.read_at: datetime.utcnow()
    })
    
    db.session.commit()

    return jsonify({
        "message": f"{count} notification(s) marked as read."
    }), 200

@notifications_bp.route('/notifications/<string:notification_id>', methods=['DELETE'])
@permission_required('notification:delete') # Permission to delete own notifications
def delete_notification(notification_id):
    """Delete a notification owned by the current user."""
    current_user = g.current_user

    notification = Notification.query.filter_by(
        id=notification_id,
        recipient_user_id=current_user.id # Ensure user can only delete their own notifications
    ).first_or_404(description="Notification not found or you do not have access to delete it.")

    db.session.delete(notification)
    db.session.commit()

    return jsonify({"message": "Notification deleted successfully."}), 200

# Note on creating notifications:
# As discussed, actual creation of Notification records will typically happen
# internally within other service/blueprint routes when specific events occur.
# You would import a helper function (e.g., from notifications.utils or a general utils)
# and call it. Example:
# from ..notifications.utils import create_internal_notification # If helper is in notifications/utils.py
# create_internal_notification(recipient_user_id=some_user_id, message="...", notification_type="...")
