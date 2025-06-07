# hms_app_pkg/utils.py
import jwt
import datetime
import uuid # For generating JTI
from functools import wraps
from flask import request, jsonify, current_app, g
from .models import User, TokenBlacklist # Import TokenBlacklist

# --- JWT Helper Functions ---
def create_access_token(user_id, user_permissions):
    """Creates a new JWT access token with a JTI claim."""
    jti = str(uuid.uuid4()) # Unique ID for this token
    payload = {
        'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=current_app.config.get('JWT_EXPIRATION_MINUTES', 30)),
        'iat': datetime.datetime.utcnow(),
        'sub': str(user_id), # User ID (subject)
        'jti': jti, # JWT ID, useful for blacklisting
        'permissions': user_permissions # List of permission strings
    }
    return jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm=current_app.config.get('JWT_ALGORITHM', 'HS256'))

def decode_access_token(token):
    """
    Decodes a JWT access token.
    Returns the payload if successful, or an error string if decoding fails.
    """
    key_to_use = current_app.config['JWT_SECRET_KEY']
    algo = current_app.config.get('JWT_ALGORITHM', 'HS256')
    try:
        payload = jwt.decode(token, key_to_use, algorithms=[algo])
        # Check if token's JTI is blacklisted
        if TokenBlacklist.query.filter_by(jti=payload.get('jti')).first():
            current_app.logger.info(f"Attempt to use blacklisted token (jti: {payload.get('jti')})")
            return "Token has been revoked (logged out)."
        return payload
    except jwt.ExpiredSignatureError:
        current_app.logger.info("Token decode failed: ExpiredSignatureError")
        return "Token has expired. Please log in again."
    except jwt.InvalidSignatureError:
        current_app.logger.warning("Token decode failed: InvalidSignatureError (Wrong secret key or tampered token)")
        return "Invalid token signature. Please log in again."
    except jwt.DecodeError as e: # More specific error for decoding issues
        current_app.logger.warning(f"Token decode failed: DecodeError - {e}")
        return "Invalid token format. Please log in again."
    except Exception as e: # Catch any other potential jwt library errors
        current_app.logger.error(f"Unexpected error decoding token: {e}")
        return "Invalid token. Please log in again."

# --- Refresh Token Functions ---
def create_refresh_token(user_id):
    """Creates a new JWT refresh token."""
    jti = str(uuid.uuid4())
    payload = {
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=current_app.config.get('JWT_REFRESH_TOKEN_EXPIRES_DAYS', 7)),
        'iat': datetime.datetime.utcnow(),
        'sub': str(user_id),
        'jti': jti,
        'type': 'refresh' # Differentiate from access token
    }
    return jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm=current_app.config.get('JWT_ALGORITHM', 'HS256'))

def verify_refresh_token(token):
    """
    Verifies a refresh token. Returns payload or raises JWT specific exception on failure.
    """
    key_to_use = current_app.config['JWT_SECRET_KEY']
    algo = current_app.config.get('JWT_ALGORITHM', 'HS256')
    try:
        payload = jwt.decode(token, key_to_use, algorithms=[algo])
        if payload.get('type') != 'refresh':
            current_app.logger.warning("Invalid token type provided to verify_refresh_token.")
            raise jwt.InvalidTokenError("Not a valid refresh token.")
        # Optional: Check if refresh token jti is blacklisted if you implement that
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, jwt.DecodeError) as e:
        current_app.logger.warning(f"Refresh token verification failed: {e}")
        raise # Re-raise the specific JWT error to be caught by the route

# --- Email Utility ---
def send_password_reset_email(user_email, reset_token): # Placeholder
    """Simulates sending a password reset email."""
    # In a real app, integrate with an email service (e.g., Flask-Mail, SendGrid, Mailgun)
    # The frontend_url should come from config for different environments
    frontend_url = current_app.config.get('FRONTEND_URL', 'http://localhost:3000') # Example frontend
    reset_url = f"{frontend_url}/reset-password?token={reset_token}"
    
    email_body = (
        f"Hello,\n\n"
        f"You requested a password reset for your HMS account.\n"
        f"Please click the link below to reset your password:\n"
        f"{reset_url}\n\n"
        f"This link will expire in {current_app.config.get('PASSWORD_RESET_TOKEN_EXPIRES_HOURS', 1)} hour(s).\n"
        f"If you did not request this, please ignore this email.\n\n"
        f"Thanks,\nThe HMS Team"
    )
    
    # Simulate sending email by printing to console
    print("--- SIMULATING PASSWORD RESET EMAIL ---")
    print(f"To: {user_email}")
    print(f"Subject: HMS - Password Reset Request")
    print(email_body)
    print("------------------------------------")
    current_app.logger.info(f"Password reset email simulated for: {user_email}. Token: {reset_token}")
    return True # Simulate success

# --- Current User Utility & RBAC Decorator (Largely unchanged but uses updated decode_access_token) ---
def get_current_user_from_token():
    auth_header = request.headers.get('Authorization')
    token = None
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(" ")[1]

    if not token:
        g.authentication_error = "Token is missing!"
        return None

    payload = decode_access_token(token) # This now checks blacklist
    if isinstance(payload, str): # Error message returned
        g.authentication_error = payload
        return None

    user_id_str = payload.get('sub')
    if not user_id_str:
        g.authentication_error = "Invalid token payload (subject missing)!"
        return None
    
    try:
        user_id = int(user_id_str)
        user = User.query.get(user_id)
        if not user:
            g.authentication_error = "User from token not found in database."
            return None
        if not user.is_active:
            g.authentication_error = "User account is inactive."
            return None
        
        g.token_permissions = payload.get('permissions', [])
        g.current_token_jti = payload.get('jti') # Store JTI from token for logout
        g.current_token_exp = payload.get('exp') # Store EXP from token for logout
        return user
    except ValueError:
        g.authentication_error = "Invalid user ID format in token."
        return None

def parse_iso_datetime(dt_str):
    """Helper: Parse ISO string, returns None on failure."""
    if not dt_str or not isinstance(dt_str, str):
        return None
    try:
        return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None
    
def permission_required(required_permission):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            current_user = get_current_user_from_token() # This sets g.authentication_error on failure

            if not current_user:
                error_message = getattr(g, 'authentication_error', "Authentication required.")
                return jsonify({"message": error_message}), 401

            g.current_user = current_user # Make user object available via g
            
            user_permissions = getattr(g, 'token_permissions', []) # Permissions from the token

            if required_permission not in user_permissions:
                return jsonify({"message": f"Permission '{required_permission}' required. You have: {user_permissions}"}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator
