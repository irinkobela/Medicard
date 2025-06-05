from flask import Blueprint, request, jsonify, current_app
from .. import db
from ..models import Task, User, Patient # Make sure Patient model is imported
from ..utils import permission_required, decode_access_token # Using our existing utils
from sqlalchemy.orm import joinedload # For eager loading assigned_to and created_by users
from datetime import datetime, timedelta # Python's datetime, not flask_jwt_extended's

tasks_bp = Blueprint('tasks_bp', __name__) # Changed 'tasks' to 'tasks_bp' to match __init__.py registration

# Helper function to get user_id from token (this should ideally be in utils.py)
def get_user_id_from_token_for_tasks():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None, jsonify({"message": "Authorization token is missing or badly formatted."}), 401
    
    token = auth_header.split(" ")[1]
    payload = decode_access_token(token) # from our utils.py
    if isinstance(payload, str): # Error message from decode_access_token
        return None, jsonify({"message": payload}), 401
    
    user_id_str = payload.get('sub')
    if not user_id_str:
        return None, jsonify({"message": "User ID (sub) missing in token."}), 401
    
    try:
        user_id = int(user_id_str)
        return user_id, None, None # user_id, error_response, status_code
    except ValueError:
        current_app.logger.error(f"Could not convert sub claim '{user_id_str}' to int.")
        return None, jsonify({"message": "Invalid user ID format in token."}), 401

@tasks_bp.route('/tasks', methods=['GET'])
@permission_required('task:read:own') # Base permission, more logic inside
def get_all_tasks():
    user_id_requesting, error_response, status_code = get_user_id_from_token_for_tasks()
    if error_response:
        return error_response, status_code

    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1] if auth_header and auth_header.startswith('Bearer ') else None
    requesting_user_permissions = []
    if token:
        payload = decode_access_token(token)
        if isinstance(payload, dict):
            requesting_user_permissions = payload.get('permissions', [])
    
    can_read_any = 'task:read:any' in requesting_user_permissions
    query = Task.query.options(joinedload(Task.assigned_to), joinedload(Task.created_by)) # Eager load user details

    # Filtering logic from our previous combined version
    assigned_to_filter = request.args.get('assigned_to_user_id')
    patient_id_filter = request.args.get('patient_id')
    completed_filter = request.args.get('completed') # string 'true' or 'false'
    priority_filter = request.args.get('priority')
    department_filter = request.args.get('department') # New filter

    if assigned_to_filter:
        if assigned_to_filter.lower() == 'me':
            query = query.filter(Task.assigned_to_user_id == user_id_requesting)
        else:
            if not can_read_any:
                return jsonify({"message": "Permission 'task:read:any' required to view tasks for other users."}), 403
            try:
                query = query.filter(Task.assigned_to_user_id == int(assigned_to_filter))
            except ValueError:
                return jsonify({"message": "Invalid assigned_to_user_id filter format."}), 400
    elif patient_id_filter:
        if not can_read_any: # Simplified: need 'any' to filter by patient unless it's your own task (more complex)
             query = query.filter(Task.patient_id == patient_id_filter, Task.assigned_to_user_id == user_id_requesting)
             # A more robust check would be if the user is part of the patient's care team.
             # For now, if not task:read:any, they can only see tasks for a patient if assigned to them.
             # If they have task:read:any, they can see all tasks for that patient.
        else:
            query = query.filter(Task.patient_id == patient_id_filter)

    elif not can_read_any: # Default for users with only 'task:read:own'
        query = query.filter(Task.assigned_to_user_id == user_id_requesting)
    
    if completed_filter is not None:
        if completed_filter.lower() == 'true':
            query = query.filter(Task.completed == True)
        elif completed_filter.lower() == 'false':
            query = query.filter(Task.completed == False)
    
    if priority_filter:
        query = query.filter(Task.priority.ilike(f'%{priority_filter}%'))
    if department_filter:
        query = query.filter(Task.department.ilike(f'%{department_filter}%'))

    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    tasks_pagination = query.order_by(Task.due_datetime.asc().nullslast(), Task.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        "tasks": [task.to_dict() for task in tasks_pagination.items],
        "total": tasks_pagination.total,
        "page": tasks_pagination.page,
        "per_page": tasks_pagination.per_page,
        "pages": tasks_pagination.pages
    }), 200


@tasks_bp.route('/tasks/<string:task_id>', methods=['GET'])
@permission_required('task:read:own') # Base permission, more detailed check inside
def get_task(task_id):
    user_id_requesting, error_response, status_code = get_user_id_from_token_for_tasks()
    if error_response: return error_response, status_code

    task = Task.query.options(joinedload(Task.assigned_to), joinedload(Task.created_by)).get_or_404(task_id)

    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1] if auth_header and auth_header.startswith('Bearer ') else None
    requesting_user_permissions = []
    if token:
        payload = decode_access_token(token)
        if isinstance(payload, dict): requesting_user_permissions = payload.get('permissions', [])
    can_read_any = 'task:read:any' in requesting_user_permissions

    if not (task.assigned_to_user_id == user_id_requesting or \
            task.created_by_user_id == user_id_requesting or \
            can_read_any or \
            (task.visibility == 'public' or (task.visibility == 'team' # Add team check logic here
             ))): # Simplified visibility check
        return jsonify({"message": "Unauthorized to view this specific task."}), 403
        
    return jsonify(task.to_dict()), 200


@tasks_bp.route('/tasks', methods=['POST'])
@permission_required('task:create')
def create_task():
    user_id_creating, error_response, status_code = get_user_id_from_token_for_tasks()
    if error_response:
        return error_response, status_code

    data = request.get_json()
    title = data.get('title')
    if not title:
        return jsonify({"message": "Title is required."}), 400

    due_datetime_val = None
    if data.get('due_datetime'):
        try:
            due_datetime_val = datetime.fromisoformat(data['due_datetime'].replace('Z', '+00:00')) if data['due_datetime'] else None
        except ValueError:
            return jsonify({"message": "Invalid due_datetime format. Use ISO format."}), 400
            
    # Validate assigned_to_user_id if provided
    assigned_to_user_id_val = data.get('assigned_to_user_id')
    if assigned_to_user_id_val and not User.query.get(assigned_to_user_id_val):
        return jsonify({"message": "Assigned user not found."}), 404
        
    # Validate patient_id if provided
    patient_id_val = data.get('patient_id')
    if patient_id_val and not Patient.query.get(patient_id_val):
        return jsonify({"message": "Patient not found."}), 404

    new_task = Task(
        title=title,
        description=data.get('description'),
        due_datetime=due_datetime_val,
        patient_id=patient_id_val,
        assigned_to_user_id=assigned_to_user_id_val,
        priority=data.get('priority', 'Normal'),
        category=data.get('category'),
        department=data.get('department'),
        created_by_user_id=user_id_creating, # Correctly use the creator's ID
        is_urgent=data.get('is_urgent', False),
        visibility=data.get('visibility', 'private'), # Default to private
        status = data.get('status', 'Pending') # Default status
    )
    db.session.add(new_task)
    db.session.commit()
    return jsonify(new_task.to_dict()), 201


@tasks_bp.route('/tasks/<string:task_id>', methods=['PUT'])
@permission_required('task:update:own') # Base, more checks inside
def update_task(task_id):
    task = Task.query.get_or_404(task_id)
    user_id_requesting, error_response, status_code = get_user_id_from_token_for_tasks()
    if error_response: return error_response, status_code

    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1] if auth_header and auth_header.startswith('Bearer ') else None
    requesting_user_permissions = []
    if token:
        payload = decode_access_token(token)
        if isinstance(payload, dict): requesting_user_permissions = payload.get('permissions', [])
    can_update_any = 'task:update:any' in requesting_user_permissions

    if not (task.assigned_to_user_id == user_id_requesting or \
            task.created_by_user_id == user_id_requesting or \
            can_update_any):
        return jsonify({"message": "Unauthorized to update this task."}), 403

    data = request.get_json()
    task.title = data.get('title', task.title)
    task.description = data.get('description', task.description)
    if data.get('due_datetime'):
        try:
            task.due_datetime = datetime.fromisoformat(data['due_datetime'].replace('Z', '+00:00')) if data['due_datetime'] else None
        except ValueError:
            return jsonify({"message": "Invalid due_datetime format for update."}), 400
    
    if 'patient_id' in data: # Allow changing patient association
        if data['patient_id'] and not Patient.query.get(data['patient_id']):
            return jsonify({"message": "New patient not found."}), 404
        task.patient_id = data['patient_id']

    if 'assigned_to_user_id' in data: # Allow re-assigning
        if data['assigned_to_user_id'] and not User.query.get(data['assigned_to_user_id']):
            return jsonify({"message": "New assigned user not found."}), 404
        task.assigned_to_user_id = data['assigned_to_user_id']
        
    task.priority = data.get('priority', task.priority)
    task.category = data.get('category', task.category)
    task.department = data.get('department', task.department)
    task.status = data.get('status', task.status)
    task.visibility = data.get('visibility', task.visibility)
    task.is_urgent = data.get('is_urgent', task.is_urgent)

    if task.status == 'Completed' and not task.completed:
        task.completed = True
        task.completed_at = datetime.utcnow()
    elif task.status != 'Completed' and task.completed: # If status changed from completed
        task.completed = False
        task.completed_at = None

    db.session.commit()
    return jsonify(task.to_dict()), 200


@tasks_bp.route('/tasks/<string:task_id>', methods=['DELETE'])
@permission_required('task:delete:own') # Base, more checks inside
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    user_id_requesting, error_response, status_code = get_user_id_from_token_for_tasks()
    if error_response: return error_response, status_code

    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1] if auth_header and auth_header.startswith('Bearer ') else None
    requesting_user_permissions = []
    if token:
        payload = decode_access_token(token)
        if isinstance(payload, dict): requesting_user_permissions = payload.get('permissions', [])
    can_delete_any = 'task:delete:any' in requesting_user_permissions

    if not (task.created_by_user_id == user_id_requesting or can_delete_any):
        return jsonify({"message": "Unauthorized to delete this task."}), 403
        
    db.session.delete(task)
    db.session.commit()
    return jsonify({"message": "Task deleted"}), 200


@tasks_bp.route('/tasks/<string:task_id>/complete', methods=['PATCH'])
@permission_required('task:update:own') # Or a more specific task:complete
def mark_task_complete(task_id):
    task = Task.query.get_or_404(task_id)
    user_id_requesting, error_response, status_code = get_user_id_from_token_for_tasks()
    if error_response: return error_response, status_code

    # Authorization: typically assignee or creator can complete
    if not (task.assigned_to_user_id == user_id_requesting or task.created_by_user_id == user_id_requesting or \
            'task:update:any' in (decode_access_token(request.headers.get('Authorization').split(" ")[1]) or {}).get('permissions',[])): # Check for broader permission
        return jsonify({"message": "Unauthorized to complete this task."}), 403

    if task.completed:
        return jsonify({"message": "Task already completed."}), 400

    task.completed = True
    task.completed_at = datetime.utcnow()
    task.status = 'Completed'
    db.session.commit()
    return jsonify(task.to_dict()), 200


@tasks_bp.route('/tasks/departments', methods=['GET'])
@permission_required('task:read:any') # Usually requires broader view
def get_tasks_by_department():
    department = request.args.get('department')
    if not department:
        return jsonify({"message": "Department query parameter is required."}), 400

    tasks = Task.query.filter(Task.department.ilike(f'%{department}%')).all()
    return jsonify([task.to_dict() for task in tasks]), 200


@tasks_bp.route('/tasks/<string:task_id>/status', methods=['PATCH'])
@permission_required('task:update:own') # Or a more specific task:change_status
def update_task_status(task_id):
    task = Task.query.get_or_404(task_id)
    user_id_requesting, error_response, status_code = get_user_id_from_token_for_tasks()
    if error_response: return error_response, status_code

    # Authorization check (similar to update_task)
    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1] if auth_header and auth_header.startswith('Bearer ') else None
    requesting_user_permissions = []
    if token:
        payload = decode_access_token(token)
        if isinstance(payload, dict): requesting_user_permissions = payload.get('permissions', [])
    can_update_any = 'task:update:any' in requesting_user_permissions

    if not (task.assigned_to_user_id == user_id_requesting or \
            task.created_by_user_id == user_id_requesting or \
            can_update_any):
        return jsonify({"message": "Unauthorized to update status of this task."}), 403

    data = request.get_json()
    new_status = data.get('status')
    valid_statuses = ['Pending', 'In Progress', 'Completed', 'Cancelled', 'On Hold'] # Define your valid statuses
    if not new_status or new_status not in valid_statuses:
        return jsonify({"message": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"}), 400

    task.status = new_status
    if new_status == 'Completed':
        task.completed = True
        if not task.completed_at: # Only set if not already completed
             task.completed_at = datetime.utcnow()
    elif task.completed: # If status changes from 'Completed' to something else
        task.completed = False
        task.completed_at = None
        
    db.session.commit()
    return jsonify({"message": f"Task status updated to {new_status}", "task": task.to_dict()}), 200


@tasks_bp.route('/tasks/summary', methods=['GET'])
@permission_required('task:read:any') # Summary usually requires a broader view
def task_summary():
    # This could be refined to show summary for current user, their team, etc.
    total = Task.query.count()
    pending = Task.query.filter_by(status='Pending').count()
    in_progress = Task.query.filter_by(status='In Progress').count()
    completed = Task.query.filter_by(status='Completed').count()
    cancelled = Task.query.filter_by(status='Cancelled').count()

    return jsonify({
        "total_tasks": total,
        "status_summary": {
            "pending": pending,
            "in_progress": in_progress,
            "completed": completed,
            "cancelled": cancelled
        }
    }), 200


@tasks_bp.route('/tasks/today', methods=['GET'])
@permission_required('task:read:own')
def get_today_tasks():
    user_id, error_response, status_code = get_user_id_from_token_for_tasks()
    if error_response:
        return error_response, status_code

    today_start = datetime.combine(datetime.today(), datetime.min.time())
    today_end = datetime.combine(datetime.today(), datetime.max.time())

    tasks = Task.query.filter(
        Task.assigned_to_user_id == user_id,
        Task.due_datetime >= today_start,
        Task.due_datetime <= today_end,
        Task.completed == False # Typically only show uncompleted tasks due today
    ).order_by(Task.due_datetime.asc().nullslast()).all()

    return jsonify([task.to_dict() for task in tasks]), 200