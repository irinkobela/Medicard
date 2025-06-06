# hms_app_pkg/sockets.py
from flask_socketio import SocketIO, join_room, leave_room
from flask import g, request
from .utils import decode_access_token
from .models import User

# Create the SocketIO instance but don't attach it to the app yet
socketio = SocketIO(cors_allowed_origins="*") # Use a specific origin in production

@socketio.on('connect')
def handle_connect():
    """
    Handles a new client connection.
    The client must provide a valid JWT to be placed in a user-specific "room".
    """
    access_token = request.args.get('token')
    if not access_token:
        return False # Reject connection if no token is provided

    payload = decode_access_token(access_token)
    if isinstance(payload, str) or not payload.get('sub'):
        return False # Reject connection if token is invalid

    user = User.query.get(int(payload['sub']))
    if not user:
        return False # Reject connection if user doesn't exist

    # The "room" is a private channel for this specific user.
    # The server can send messages to this room, and only this user will receive them.
    join_room(user.id)
    print(f"Socket.IO Client connected: user_id {user.id} joined room {user.id}")


@socketio.on('disconnect')
def handle_disconnect():
    # In a more complex app, you might want to leave the room here,
    # but Socket.IO handles room cleanup on disconnect automatically.
    print(f"Socket.IO Client disconnected")