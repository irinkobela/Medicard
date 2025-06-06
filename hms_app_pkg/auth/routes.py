# hms_app_pkg/auth/routes.py
from flask import Blueprint, request, jsonify, current_app, g
from .. import db
from ..models import User, Role, TokenBlacklist
from ..utils import create_access_token, permission_required, decode_access_token, \
                    create_refresh_token, verify_refresh_token, send_password_reset_email
from sqlalchemy.exc import IntegrityError
import datetime
import uuid
import jwt 
from ..audit.services import create_audit_log 

auth_bp = Blueprint('auth_bp', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data: return jsonify({"message": "Request body must be JSON."}), 400
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    full_name = data.get('full_name', '')

    if not all([username, email, password]):
        return jsonify({"message": "Username, email, and password are required."}), 400

    if len(password) < 8: # Basic password policy
        return jsonify({"message": "Password must be at least 8 characters long."}), 400

    if User.query.filter((User.username == username) | (User.email == email)).first():
        return jsonify({"message": "User with this username or email already exists."}), 409

    try:
        new_user = User(username=username, email=email, full_name=full_name)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        current_app.logger.info(f"New user registered: {username}")
        return jsonify({
            "message": "User registered successfully.",
            "user": new_user.to_dict(include_permissions=False, include_roles=False)
        }), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error during registration for {username}: {e}")
        return jsonify({"message": "An error occurred during registration."}), 500

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data: return jsonify({"message": "Request body must be JSON."}), 400
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({"message": "Username and password are required."}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        current_app.logger.warning(f"Failed login attempt for username: {username}")
        return jsonify({"message": "Invalid username or password."}), 401
    if not user.is_active:
        current_app.logger.warning(f"Inactive user login attempt: {username}")
        return jsonify({"message": "User account is inactive."}), 403

    if user.mfa_enabled:
        current_app.logger.info(f"MFA required for user: {username}")
        return jsonify({"message": "MFA verification required.", "mfa_required": True, "user_id": user.id}), 202

    user_permissions = user.get_permissions()
    access_token = create_access_token(user_id=user.id, user_permissions=user_permissions)
    refresh_token_str = create_refresh_token(user_id=user.id)

    current_app.logger.info(f"User '{username}' logged in successfully.")
    return jsonify({
        "message": "Login successful.",
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "user": user.to_dict(include_permissions=True, include_roles=True)
    }), 200

@auth_bp.route('/login/mfa-verify', methods=['POST'])
def mfa_verify():
    # ... (Placeholder for actual TOTP verification logic) ...
    return jsonify({"message": "MFA verification logic not fully implemented yet."}), 501


@auth_bp.route('/logout', methods=['POST'])
@permission_required('user:logout')
def logout():
    jti = getattr(g, 'current_token_jti', None)
    token_exp = None # Will try to get it from the token if not on g

    # Try to get expiry from g, if utils.py sets it. Otherwise, re-decode carefully.
    # For now, let's assume it's not on g and we re-decode.
    auth_header = request.headers.get('Authorization')
    token_str = auth_header.split(" ")[1] if auth_header and auth_header.startswith('Bearer ') else None

    if not token_str and not jti : # If no JTI from g and no token string, something is wrong.
         return jsonify({"message": "Token information unavailable for logout."}), 400
    
    if not jti and token_str: # If JTI wasn't on g, but we have the token string
        try:
            # Decode just to get jti and exp, without blacklist check here
            temp_payload = jwt.decode(token_str, current_app.config['JWT_SECRET_KEY'], algorithms=[current_app.config['JWT_ALGORITHM']], options={"verify_exp": False})
            jti = temp_payload.get('jti')
            token_exp = temp_payload.get('exp')
        except Exception as e:
            current_app.logger.warning(f"Could not decode token during logout to get JTI/EXP: {e}")
            # Proceed without exp if jti is still somehow available (e.g., if g.current_token_jti was set but not exp)
            # Or return error if jti cannot be obtained.
            if not jti:
                return jsonify({"message": "Could not process token for logout."}), 400
    
    if not jti: # Final check for JTI
        return jsonify({"message": "Token JTI could not be determined for logout."}), 400
    
    # Determine expiry. If token_exp wasn't found, we can't effectively blacklist with expiry.
    # A safer default could be to blacklist for a short period or rely on DB cleanup.
    # For simplicity, if token_exp is still None, the TokenBlacklist entry might lack a precise expiry.
    # The TokenBlacklist model requires expires_at, so we must have it.
    if token_exp is None: # This should ideally not happen if token is valid
        current_app.logger.error(f"Could not determine token expiry for JTI {jti} during logout.")
        return jsonify({"message": "Failed to determine token expiry for logout."}), 500

    try:
        blacklisted_token = TokenBlacklist.query.filter_by(jti=jti).first()
        if blacklisted_token:
            current_app.logger.info(f"Token JTI {jti} already blacklisted.")
            return jsonify({"message": "Already logged out or token revoked."}), 200 # Or 400 if considered an error

        new_blacklist_entry = TokenBlacklist(jti=jti, expires_at=datetime.datetime.utcfromtimestamp(token_exp))
        db.session.add(new_blacklist_entry)
        db.session.commit()
        current_app.logger.info(f"User {g.current_user.id if hasattr(g, 'current_user') else 'Unknown'} logged out. Token JTI {jti} blacklisted.")
        return jsonify({"message": "Logged out successfully."}), 200
    except IntegrityError: 
        db.session.rollback()
        current_app.logger.warning(f"IntegrityError: Attempt to re-blacklist token JTI: {jti}")
        return jsonify({"message": "Token already revoked or error blacklisting."}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Logout error for JTI {jti}: {e}")
        return jsonify({"message": "Failed to process logout due to an internal error."}), 500


@auth_bp.route('/refresh-token', methods=['POST'])
def refresh_token_route():
    data = request.get_json()
    if not data or 'refresh_token' not in data:
        return jsonify({"message": "Refresh token is required."}), 400

    refresh_token_str = data['refresh_token']
    try:
        payload = verify_refresh_token(refresh_token_str)
        user_id = int(payload['sub'])
        user = User.query.get(user_id)
        if not user or not user.is_active:
            return jsonify({"message": "User not found or inactive."}), 401

        new_access_token = create_access_token(user_id=user.id, user_permissions=user.get_permissions())
        current_app.logger.info(f"Access token refreshed for user ID: {user_id}")
        return jsonify({"access_token": new_access_token}), 200
    except jwt.ExpiredSignatureError:
        return jsonify({"message": "Refresh token has expired."}), 401
    except jwt.InvalidTokenError as e:
        current_app.logger.error(f"Refresh token error: {e}")
        return jsonify({"message": "Invalid or malformed refresh token."}), 401
    except Exception as e:
        current_app.logger.error(f"Unexpected refresh token error: {e}")
        return jsonify({"message": "Failed to refresh token."}), 500


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json()
    email = data.get('email') if data else None
    if not email:
        return jsonify({"message": "Email address is required."}), 400

    user = User.query.filter_by(email=email).first()
    if user:
        try:
            reset_token = str(uuid.uuid4())
            user.password_reset_token = reset_token
            user.password_reset_expires = datetime.datetime.utcnow() + datetime.timedelta(
                hours=current_app.config.get('PASSWORD_RESET_TOKEN_EXPIRES_HOURS', 1)
            )
            db.session.commit()
            
            send_password_reset_email(user.email, reset_token)
            current_app.logger.info(f"Password reset email simulated for: {email}")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error during forgot password for {email}: {e}")
    
    return jsonify({"message": "If an account with that email exists, a password reset link has been sent."}), 200


@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json()
    token = data.get('token')
    new_password = data.get('new_password')

    if not token or not new_password:
        return jsonify({"message": "Token and new password are required."}), 400

    if len(new_password) < 8: # Basic password policy
         return jsonify({"message": "New password must be at least 8 characters long."}), 400

    user = User.query.filter_by(password_reset_token=token).first()

    if not user or not user.password_reset_expires or user.password_reset_expires < datetime.datetime.utcnow():
        current_app.logger.warning(f"Invalid or expired password reset token attempt: {token}")
        return jsonify({"message": "Password reset token is invalid or has expired."}), 400

    try:
        user.set_password(new_password)
        user.password_reset_token = None
        user.password_reset_expires = None
        db.session.commit()
        current_app.logger.info(f"Password reset successfully for user ID: {user.id}")
        return jsonify({"message": "Password has been reset successfully."}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error resetting password for token {token}: {e}")
        return jsonify({"message": "An error occurred while resetting the password."}), 500


@auth_bp.route('/me', methods=['GET'])
@permission_required('user:profile:read')
def get_current_user_profile():
    current_user = g.current_user
    return jsonify(current_user.to_dict(include_permissions=True, include_roles=True))

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data: return jsonify({"message": "Request body must be JSON."}), 400

    # --- FIX: Define username and password from the request data FIRST ---
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({"message": "Username and password are required."}), 400

    user = User.query.filter_by(username=username).first()

    # --- FIX: Check the password right after finding the user ---
    if not user or not user.check_password(password):
        # We can log the FAILED login attempt here
        create_audit_log(
            action="LOGIN_FAILURE",
            change_details={"username_attempt": username, "message": "Invalid username or password."}
        )
        db.session.commit()
        current_app.logger.warning(f"Failed login attempt for username: {username}")
        return jsonify({"message": "Invalid username or password."}), 401

    if not user.is_active:
        current_app.logger.warning(f"Inactive user login attempt: {username}")
        return jsonify({"message": "User account is inactive."}), 403

    if user.mfa_enabled:
        # MFA logic is correct as is
        current_app.logger.info(f"MFA required for user: {username}")
        return jsonify({"message": "MFA verification required.", "mfa_required": True, "user_id": user.id}), 202

   #The audit log for SUCCESSFUL login now goes HERE ---
    # The user has been fully authenticated at this point.
    g.current_user = user # Set the user in 'g' so our audit service can find it
    create_audit_log(action="LOGIN_SUCCESS")
    db.session.commit() # Commit the audit log entry

    user_permissions = user.get_permissions()
    access_token = create_access_token(user_id=user.id, user_permissions=user_permissions)
    refresh_token_str = create_refresh_token(user_id=user.id)

    current_app.logger.info(f"User '{username}' logged in successfully.")
    return jsonify({
        "message": "Login successful.",
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "user": user.to_dict(include_permissions=True, include_roles=True)
    }), 200