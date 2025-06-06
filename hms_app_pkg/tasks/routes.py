# hms_app_pkg/tasks/routes.py
from flask import Blueprint, request, jsonify, current_app, g
from .. import db
from ..models import Task, User, Patient
from ..utils import permission_required
from ..services import create_notification # <<< IMPORT THE NOTIFICATION SERVICE
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
import datetime

tasks_bp = Blueprint('tasks_bp', __name__)

# The local helper function get_user_id_from_token_for_tasks() is removed.
# We will use g.current_user set by the permission_required decorator from utils.py.

@tasks_bp.route('/tasks', methods=['POST'])
@permission_required('task:create') 
def create_task():
    user_creating = g.current_user 
    if not user_creating:
        return jsonify({"message": "Authentication error, current user not found."}), 401

    data = request.get_json()
    if not data or not data.get('title') or not data.get('assigned_to_user_id'):
        return jsonify({"message": "title and assigned_to_user_id are required."}), 400

    assigned_user = User.query.get(data['assigned_to_user_id'])
    if not assigned_user:
        return jsonify({"message": "Assigned user not found."}), 404

    patient_id = data.get('patient_id')
    if patient_id and not Patient.query.get(patient_id):
        return jsonify({"message": "Patient not found."}), 404
    
    due_datetime_val = None
    if data.get('due_datetime'):
        try:
            due_datetime_str = data['due_datetime']
            if not isinstance(due_datetime_str, str): raise ValueError("Date must be a string")
            if '.' in due_datetime_str:
                due_datetime_val = datetime.datetime.strptime(due_datetime_str, '%Y-%m-%dT%H:%M:%S.%f')
            else:
                due_datetime_val = datetime.datetime.strptime(due_datetime_str, '%Y-%m-%dT%H:%M:%S')
        except (ValueError, TypeError):
            return jsonify({"message": "Invalid due_datetime format. Use ISO format."}), 400

    try:
        new_task = Task(
            title=data['title'],
            assigned_to_user_id=assigned_user.id,
            created_by_user_id=user_creating.id,
            description=data.get('description'),
            patient_id=patient_id,
            due_datetime=due_datetime_val,
            priority=data.get('priority', 'Normal'),
            category=data.get('category'),
            department=data.get('department'),
            status=data.get('status', 'Pending'),
            is_urgent=data.get('is_urgent', False),
            visibility=data.get('visibility', 'private')
        )
        db.session.add(new_task)
        db.session.commit()

        # --- NOTIFICATION TRIGGER LOGIC ---
        # If a user assigns a task to someone else, notify the assignee.
        if new_task.assigned_to_user_id != user_creating.id:
            create_notification(
                recipient_user_ids=new_task.assigned_to_user_id,
                message_template="You have been assigned a new task by {creator_name}: '{task_title}'",
                template_context={
                    "creator_name": user_creating.full_name or user_creating.username,
                    "task_title": new_task.title
                },
                notification_type="NEW_TASK_ASSIGNMENT",
                link_to_item_type="Task",
                link_to_item_id=new_task.id,
                related_patient_id=new_task.patient_id,
                is_urgent=new_task.is_urgent
            )
        # --- END NOTIFICATION TRIGGER ---
            
        return jsonify({"message": "Task created successfully", "task": new_task.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating task: {e}")
        return jsonify({"message": "An unexpected error occurred while creating the task."}), 500


@tasks_bp.route('/tasks', methods=['GET'])
@permission_required('task:read:own')
def get_tasks():
    current_user = g.current_user
    requesting_user_permissions = getattr(g, 'token_permissions', [])
    can_read_any = 'task:read:any' in requesting_user_permissions

    query = Task.query.options(joinedload(Task.assigned_to), joinedload(Task.created_by))
    
    assigned_to_filter = request.args.get('assigned_to_user_id')
    patient_id_filter = request.args.get('patient_id')
    completed_filter_str = request.args.get('completed')
    priority_filter = request.args.get('priority')
    department_filter = request.args.get('department')

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
        if not can_read_any:
             query = query.filter(Task.patient_id == patient_id_filter, Task.assigned_to_user_id == current_user.id)
        else:
            query = query.filter(Task.patient_id == patient_id_filter)
    elif not can_read_any:
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
        "total": tasks_pagination.total,
        "page": tasks_pagination.page,
        "per_page": tasks_pagination.per_page,
        "pages": tasks_pagination.pages
    }), 200

@tasks_bp.route('/tasks/<string:task_id>', methods=['GET'])
@permission_required('task:read:own')
def get_task(task_id):
    current_user = g.current_user
    task = Task.query.options(joinedload(Task.assigned_to), joinedload(Task.created_by)).get_or_404(task_id)
    
    requesting_user_permissions = getattr(g, 'token_permissions', [])
    can_read_any = 'task:read:any' in requesting_user_permissions

    if not (task.assigned_to_user_id == current_user.id or \
            task.created_by_user_id == current_user.id or \
            can_read_any or \
            (task.visibility == 'public')):
        return jsonify({"message": "Unauthorized to view this specific task."}), 403
        
    return jsonify(task.to_dict()), 200

@tasks_bp.route('/tasks/<string:task_id>', methods=['PUT'])
@permission_required('task:update:own')
def update_task(task_id):
    current_user = g.current_user
    task = Task.query.get_or_404(task_id)
    
    requesting_user_permissions = getattr(g, 'token_permissions', [])
    can_update_any = 'task:update:any' in requesting_user_permissions

    if not (task.assigned_to_user_id == current_user.id or \
            task.created_by_user_id == current_user.id or \
            can_update_any):
        return jsonify({"message": "Unauthorized to update this task."}), 403

    data = request.get_json()
    if not data: return jsonify({"message": "No update data provided"}), 400
    
    # Check if a notification is needed for re-assignment
    old_assignee = task.assigned_to_user_id
    new_assignee = data.get('assigned_to_user_id')
    
    if 'title' in data: task.title = data['title']
    if 'description' in data: task.description = data['description']
    if 'priority' in data: task.priority = data['priority']
    if 'category' in data: task.category = data['category']
    if 'department' in data: task.department = data['department']
    if 'status' in data: task.status = data['status']
    if 'is_urgent' in data and isinstance(data['is_urgent'], bool): task.is_urgent = data['is_urgent']
    if 'visibility' in data: task.visibility = data['visibility']
    
    if 'assigned_to_user_id' in data:
        if new_assignee is not None:
            if not User.query.get(new_assignee):
                return jsonify({"message": "New assigned user not found."}), 404
            task.assigned_to_user_id = new_assignee
        else:
            task.assigned_to_user_id = None

    if 'due_datetime' in data:
        if data['due_datetime'] is None:
            task.due_datetime = None
        else:
            try:
                task.due_datetime = datetime.datetime.fromisoformat(data['due_datetime'].replace('Z', '+00:00'))
            except (ValueError, TypeError):
                return jsonify({"message": "Invalid due_datetime format."}), 400
    
    if 'completed' in data and isinstance(data['completed'], bool):
        if data['completed'] and not task.completed:
            task.completed = True
            task.completed_at = datetime.datetime.utcnow()
            task.status = "Completed"
        elif not data['completed'] and task.completed:
            task.completed = False
            task.completed_at = None
            if task.status == "Completed": task.status = "In Progress"
            
    if task.status == "Completed" and not task.completed:
        task.completed = True
        if not task.completed_at: task.completed_at = datetime.datetime.utcnow()
    elif task.status != "Completed" and task.completed:
        task.completed = False
        task.completed_at = None

    task.updated_at = datetime.datetime.utcnow()
    db.session.commit()

    # --- NOTIFICATION TRIGGER FOR RE-ASSIGNMENT ---
    if new_assignee is not None and new_assignee != old_assignee and new_assignee != current_user.id:
        create_notification(
            recipient_user_ids=new_assignee,
            message_template="Task '{task_title}' has been re-assigned to you by {modifier_name}.",
            template_context={
                "task_title": task.title,
                "modifier_name": current_user.full_name or current_user.username
            },
            notification_type="TASK_ASSIGNMENT",
            link_to_item_type="Task",
            link_to_item_id=task.id,
            related_patient_id=task.patient_id,
            is_urgent=task.is_urgent
        )
    # --- END NOTIFICATION TRIGGER ---

    return jsonify({"message": "Task updated successfully", "task": task.to_dict()}), 200

@tasks_bp.route('/tasks/<string:task_id>', methods=['DELETE'])
@permission_required('task:delete:own')
def delete_task(task_id):
    current_user = g.current_user
    task = Task.query.get_or_404(task_id)
    
    requesting_user_permissions = getattr(g, 'token_permissions', [])
    can_delete_any = 'task:delete:any' in requesting_user_permissions

    if not (task.created_by_user_id == current_user.id or can_delete_any):
        return jsonify({"message": "Unauthorized to delete this task."}), 403
        
    db.session.delete(task)
    db.session.commit()
    return jsonify({"message": "Task deleted successfully"}), 200

@tasks_bp.route('/tasks/<string:task_id>/complete', methods=['PATCH'])
@permission_required('task:update:own') 
def mark_task_complete(task_id):
    current_user = g.current_user
    task = Task.query.get_or_404(task_id)

    requesting_user_permissions = getattr(g, 'token_permissions', [])
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
    
    requesting_user_permissions = getattr(g, 'token_permissions', [])
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
    elif task.completed and new_status != 'Completed':
        task.completed = False
        task.completed_at = None
    
    task.updated_at = datetime.datetime.utcnow()
    db.session.commit()
    return jsonify({"message": f"Task status updated to {new_status}", "task": task.to_dict()}), 200

@tasks_bp.route('/tasks/summary', methods=['GET'])
@permission_required('task:read:any')
def task_summary():
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
    today_start = datetime.datetime.combine(datetime.date.today(), datetime.datetime.min.time())
    today_end = datetime.datetime.combine(datetime.date.today(), datetime.datetime.max.time())

    tasks = Task.query.filter(
        Task.assigned_to_user_id == current_user.id,
        Task.due_datetime >= today_start,
        Task.due_datetime <= today_end,
        Task.completed == False
    ).order_by(Task.due_datetime.asc().nullslast()).all()

    return jsonify([task.to_dict() for task in tasks]), 200
