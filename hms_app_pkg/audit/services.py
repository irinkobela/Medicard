# hms_app_pkg/audit/services.py
from flask import request, g
from .. import db
from ..models import AuditLog

def create_audit_log(action, target_model=None, target_id=None, change_details=None, commit=False):
    """
    Creates an audit log entry.
    It automatically captures user, IP, and user agent from the request context.
    The session is not committed automatically unless specified.
    """
    user_id = None
    user_username = "system" # Default for actions without a logged-in user context

    # Safely get user info from Flask's global 'g' object
    if hasattr(g, 'current_user') and g.current_user:
        user_id = g.current_user.id
        user_username = g.current_user.username

    # Safely get request context
    ip_address = request.remote_addr if request else None
    user_agent = request.user_agent.string if request and request.user_agent else None

    log_entry = AuditLog(
        action=action,
        target_model=target_model,
        target_id=str(target_id) if target_id else None,
        change_details=change_details,
        user_id=user_id,
        user_username=user_username,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.session.add(log_entry)

    if commit:
        db.session.commit()