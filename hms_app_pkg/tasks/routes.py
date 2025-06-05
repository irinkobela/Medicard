# hms_app_pkg/tasks/routes.py
from flask import Blueprint, request, jsonify, current_app, g # Import g
from .. import db
from ..models import Task, User, Patient
from ..utils import permission_required # decode_access_token is used by permission_required in utils.py
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
import datetime
import uuid # Not strictly needed here if Task model handles UUID generation

tasks_bp = Blueprint('tasks_bp', __name__)

# The local helper function get_user_id_from_token_for_tasks() is NOW REMOVED.
# We will use g.current_user set by the permission_required decorator from utils.py.

@tasks_bp.route('/tasks', methods=['POST'])
@permission_required('task:create') 
def create_task():
    # g.current_user is set by the permission_required decorator
    user_creating = g.current_user 
    if not user_creating: # Should be caught by decorator, but an extra check
        return jsonify({"message": "Authentication error, current user not found."}), 401


    data = request.get_json()
    if not data or not data.get('title') or not data.get('assigned_to_user_id'):
        return jsonify({"message": "title and assigned_to_user_id are required."}), 400

    assigned_user = User.query.get(data['assigned_to_user_id'])
    if not assigned_user:
        return jsonify({"message": "Assigned user not found."}), 404

    patient_id = data.get('patient_id')
    if patient_id:
        patient = Patient.query.get(patient_id)
        if not patient:
            return jsonify({"message": "Patient not found."}), 404
    
    due_datetime_val = None
    if data.get('due_datetime'):
        try:
            due_datetime_str = data['due_datetime']
            if '.' in due_datetime_str:
                due_datetime_val = datetime.datetime.strptime(due_datetime_str, '%Y-%m-%dT%H:%M:%S.%f')
            else:
                due_datetime_val = datetime.datetime.strptime(due_datetime_str, '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            return jsonify({"message": "Invalid due_datetime format. Use ISO format (YYYY-MM-DDTHH:MM:SS or YYYY-MM-DDTHH:MM:SS.ffffff)."}), 400

    try:
        new_task = Task(
            title=data['title'],
            assigned_to_user_id=data['assigned_to_user_id'],
            created_by_user_id=user_creating.id, # Use ID from g.current_user
            description=data.get('description'),
            patient_id=patient_id,
            due_datetime=due_datetime_val,
            priority=data.get('priority', 'Normal'),
            category=data.get('category'),      # From updated Task model
            department=data.get('department'),  # From updated Task model
            status=data.get('status', 'Pending'), # From updated Task model
            is_urgent=data.get('is_urgent', False),# From updated Task model
            visibility=data.get('visibility', 'private') # From updated Task model
        )
        db.session.add(new_task)
        db.session.commit()
        return jsonify({"message": "Task created successfully", "task": new_task.to_dict()}), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "Database integrity error creating task."}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unexpected error creating task: {e}")
        return jsonify({"message": "An unexpected error occurred creating task."}), 500


@tasks_bp.route('/tasks', methods=['GET'])
@permission_required('task:read:own') # Base permission
def get_tasks():
    current_user = g.current_user
    requesting_user_permissions = g.token_permissions # Permissions from token set by utils.py

    query = Task.query.options(joinedload(Task.assigned_to), joinedload(Task.created_by))
    
    assigned_to_filter = request.args.get('assigned_to_user_id')
    patient_id_filter = request.args.get('patient_id')
    completed_filter_str = request.args.get('completed')
    priority_filter = request.args.get('priority')
    department_filter = request.args.get('department') # New filter from user's code

    can_read_any = 'task:read:any' in requesting_user_permissions

    if assigned_to_filter:
        if assigned_to_filter.lower() == 'me':
            query = query.filter(Task.assigned_to_user_id == current_user.id)
        else:
            if not can_read_any:
                return jsonify({"message": "Permission 'task:read:any' required to view tasks for other users."}), 403
            try:
                query = query.filter(Task.assigned_to_user_id == int(assigned_to_filter))
            except ValueError:
                return jsonify({"message": "Invalid assigned_to_user_id filter format."}), 400
    elif patient_id_filter:
        # More complex logic might be needed if 'task:read:own' means only tasks for *my* patients
        if not can_read_any:
             query = query.filter(Task.patient_id == patient_id_filter, Task.assigned_to_user_id == current_user.id)
        else: # User has 'task:read:any'
            query = query.filter(Task.patient_id == patient_id_filter)
    elif not can_read_any: # Default for users with only 'task:read:own'
        query = query.filter(Task.assigned_to_user_id == current_user.id)

    if completed_filter_str is not None:
        completed_filter = completed_filter_str.lower() == 'true'
        query = query.filter(Task.completed == completed_filter)

    if priority_filter:
        query = query.filter(Task.priority.ilike(f'%{priority_filter}%'))
    if department_filter:
        query = query.filter(Task.department.ilike(f'%{department_filter}%'))
        
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    tasks_pagination = query.order_by(Task.due_datetime.asc().nullslast(), Task.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        "tasks": [task.to_dict() for task in tasks_pagination.items],
        "total": tasks_pagination.total, "page": tasks_pagination.page,
        "per_page": tasks_pagination.per_page, "pages": tasks_pagination.pages
    }), 200

@tasks_bp.route('/tasks/<string:task_id>', methods=['GET'])
@permission_required('task:read:own')
def get_task(task_id):
    current_user = g.current_user
    task = Task.query.options(joinedload(Task.assigned_to), joinedload(Task.created_by)).get_or_404(task_id)
    
    requesting_user_permissions = g.token_permissions
    can_read_any = 'task:read:any' in requesting_user_permissions

    if not (task.assigned_to_user_id == current_user.id or \
            task.created_by_user_id == current_user.id or \
            can_read_any or \
            (task.visibility == 'public' # Add more visibility logic if needed
            )):
        return jsonify({"message": "Unauthorized to view this specific task."}), 403
        
    return jsonify(task.to_dict()), 200

@tasks_bp.route('/tasks/<string:task_id>', methods=['PUT'])
@permission_required('task:update:own')
def update_task(task_id):
    current_user = g.current_user
    task = Task.query.get_or_404(task_id)
    
    requesting_user_permissions = g.token_permissions
    can_update_any = 'task:update:any' in requesting_user_permissions

    if not (task.assigned_to_user_id == current_user.id or \
            task.created_by_user_id == current_user.id or \
            can_update_any):
        return jsonify({"message": "Unauthorized to update this task."}), 403

    data = request.get_json()
    if not data: return jsonify({"message": "No update data provided"}), 400
    
    # Update fields from your extended Task model
    if 'title' in data: task.title = data['title']
    if 'description' in data: task.description = data['description']
    if 'priority' in data: task.priority = data['priority']
    if 'category' in data: task.category = data['category']
    if 'department' in data: task.department = data['department']
    if 'status' in data: task.status = data['status']
    if 'is_urgent' in data and isinstance(data['is_urgent'], bool): task.is_urgent = data['is_urgent']
    if 'visibility' in data: task.visibility = data['visibility']
    
    if 'assigned_to_user_id' in data:
        if data['assigned_to_user_id'] is not None: # Allow unassigning by passing null
            assigned_user = User.query.get(data['assigned_to_user_id'])
            if not assigned_user: return jsonify({"message": "New assigned user not found."}), 404
            task.assigned_to_user_id = data['assigned_to_user_id']
        else:
            task.assigned_to_user_id = None


    if 'due_datetime' in data:
        if data['due_datetime'] is None:
            task.due_datetime = None
        else:
            try:
                due_datetime_str = data['due_datetime']
                if '.' in due_datetime_str:
                    task.due_datetime = datetime.datetime.strptime(due_datetime_str, '%Y-%m-%dT%H:%M:%S.%f')
                else:
                    task.due_datetime = datetime.datetime.strptime(due_datetime_str, '%Y-%m-%dT%H:%M:%S')
            except (ValueError, TypeError):
                return jsonify({"message": "Invalid due_datetime format."}), 400
    
    if 'completed' in data and isinstance(data['completed'], bool):
        if data['completed'] and not task.completed:
            task.completed = True
            task.completed_at = datetime.datetime.utcnow()
            task.status = "Completed" # Also update status
        elif not data['completed'] and task.completed:
            task.completed = False
            task.completed_at = None
            if task.status == "Completed": task.status = "In Progress" # Or "Pending"
            
    if task.status == "Completed" and not task.completed : # If status is set to completed directly
        task.completed = True
        if not task.completed_at: task.completed_at = datetime.datetime.utcnow()
    elif task.status != "Completed" and task.completed: # If status changed from completed
        task.completed = False
        task.completed_at = None


    task.updated_at = datetime.datetime.utcnow()
    db.session.commit()
    return jsonify({"message": "Task updated successfully", "task": task.to_dict()}), 200

@tasks_bp.route('/tasks/<string:task_id>', methods=['DELETE'])
@permission_required('task:delete:own')
def delete_task(task_id):
    current_user = g.current_user
    task = Task.query.get_or_404(task_id)
    
    requesting_user_permissions = g.token_permissions
    can_delete_any = 'task:delete:any' in requesting_user_permissions

    if not (task.created_by_user_id == current_user.id or can_delete_any):
        return jsonify({"message": "Unauthorized to delete this task."}), 403
        
    db.session.delete(task)
    db.session.commit()
    return jsonify({"message": "Task deleted successfully"}), 200


@tasks_bp.route('/tasks/<string:task_id>/complete', methods=['PATCH']) # Changed to PATCH
@permission_required('task:update:own') 
def mark_task_complete(task_id):
    current_user = g.current_user
    task = Task.query.get_or_404(task_id)

    requesting_user_permissions = g.token_permissions
    can_update_any = 'task:update:any' in requesting_user_permissions

    if not (task.assigned_to_user_id == current_user.id or \
            task.created_by_user_id == current_user.id or \
            can_update_any):
        return jsonify({"message": "Unauthorized to complete this task."}), 403

    if task.completed:
        return jsonify({"message": "Task already completed."}), 400

    task.completed = True
    task.completed_at = datetime.datetime.utcnow()
    task.status = 'Completed'
    task.updated_at = datetime.datetime.utcnow()
    db.session.commit()
    return jsonify(task.to_dict()), 200

@tasks_bp.route('/tasks/<string:task_id>/status', methods=['PATCH'])
@permission_required('task:update:own')
def update_task_status(task_id):
    current_user = g.current_user
    task = Task.query.get_or_404(task_id)
    
    requesting_user_permissions = g.token_permissions
    can_update_any = 'task:update:any' in requesting_user_permissions

    if not (task.assigned_to_user_id == current_user.id or \
            task.created_by_user_id == current_user.id or \
            can_update_any):
        return jsonify({"message": "Unauthorized to update status of this task."}), 403

    data = request.get_json()
    new_status = data.get('status')
    valid_statuses = ['Pending', 'In Progress', 'Completed', 'Cancelled', 'On Hold']
    if not new_status or new_status not in valid_statuses:
        return jsonify({"message": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"}), 400

    task.status = new_status
    if new_status == 'Completed':
        task.completed = True
        if not task.completed_at: task.completed_at = datetime.datetime.utcnow()
    elif task.completed and new_status != 'Completed': # If un-completing
        task.completed = False
        task.completed_at = None
    
    task.updated_at = datetime.datetime.utcnow()
    db.session.commit()
    return jsonify({"message": f"Task status updated to {new_status}", "task": task.to_dict()}), 200

@tasks_bp.route('/tasks/summary', methods=['GET'])
@permission_required('task:read:any') # Summary typically requires broader view
def task_summary():
    # Add filtering based on current_user if not admin, e.g. tasks for user's department
    # For now, global summary if 'task:read:any'
    
    total = Task.query.count()
    pending = Task.query.filter_by(status='Pending', completed=False).count()
    in_progress = Task.query.filter_by(status='In Progress', completed=False).count()
    completed_count = Task.query.filter_by(status='Completed', completed=True).count()
    cancelled = Task.query.filter_by(status='Cancelled').count()
    on_hold = Task.query.filter_by(status='On Hold').count()


    return jsonify({
        "total_tasks": total,
        "status_summary": {
            "pending": pending,
            "in_progress": in_progress,
            "completed": completed_count,
            "cancelled": cancelled,
            "on_hold": on_hold
        }
    }), 200

@tasks_bp.route('/tasks/today', methods=['GET'])
@permission_required('task:read:own')
def get_today_tasks():
    current_user = g.current_user

    today_start = datetime.combine(datetime.date.today(), datetime.time.min) # Use datetime.date.today()
    today_end = datetime.combine(datetime.date.today(), datetime.time.max)

    tasks = Task.query.filter(
        Task.assigned_to_user_id == current_user.id,
        Task.due_datetime >= today_start,
        Task.due_datetime <= today_end,
        Task.completed == False
    ).order_by(Task.due_datetime.asc().nullslast()).all()

    return jsonify([task.to_dict() for task in tasks]), 200
