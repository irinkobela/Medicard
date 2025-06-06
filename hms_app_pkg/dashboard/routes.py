# hms_app_pkg/dashboard/routes.py
from flask import Blueprint, jsonify, g
from ..models import Patient, Task, Notification, Appointment, LabResult, PatientMedication, Order
from ..utils import permission_required
from datetime import datetime, timedelta # --- FIX: Imported timedelta for date calculations

dashboard_bp = Blueprint('dashboard_bp', __name__)

@dashboard_bp.route('/dashboard', methods=['GET'])
@permission_required('dashboard:read')
def get_dashboard_data():
    """
    Aggregates and returns key information for the logged-in user's dashboard.
    """
    current_user = g.current_user

    # 1. Get a summary of assigned patients
    assigned_patients = Patient.query.filter_by(attending_physician_id=current_user.id).all()
    assigned_patient_ids = [p.id for p in assigned_patients] # Get a list of patient IDs for other queries
    patients_summary = [{
        "id": p.id,
        "mrn": p.mrn,
        "full_name": f"{p.first_name} {p.last_name}",
        "age": p.age,
        "gender": p.gender
    } for p in assigned_patients]

    # 2. Get the 10 most recent, open tasks for the user
    # --- FIX: Removed duplicated queries. We only need to get tasks and notifications once.
    open_tasks = Task.query.filter(
        Task.assigned_to_user_id == current_user.id,
        Task.completed == False
    ).order_by(Task.is_urgent.desc(), Task.due_datetime.asc().nullslast()).limit(10).all()
    tasks_summary = [task.to_dict() for task in open_tasks]

    # 3. Get the 10 most recent unread notifications and a total count
    unread_notifications = Notification.query.filter(
        Notification.recipient_user_id == current_user.id,
        Notification.is_read == False
    ).order_by(Notification.is_urgent.desc(), Notification.created_at.desc()).limit(10).all()
    notifications_summary = [n.to_dict() for n in unread_notifications]

    unread_count = Notification.query.filter_by(
        recipient_user_id=current_user.id,
        is_read=False
    ).count()

    # 4. Upcoming appointments (next 5)
    # --- FIX: Changed Appointment.doctor_id to provider_user_id and start_time to start_datetime
    upcoming_appointments = Appointment.query.filter(
        Appointment.provider_user_id == current_user.id,
        Appointment.start_datetime >= datetime.utcnow()
    ).order_by(Appointment.start_datetime.asc()).limit(5).all()
    appointments_summary = [appt.to_dict(include_related=True) for appt in upcoming_appointments]


    # 5. Recent lab results for assigned patients (last 7 days)
    # --- FIX: Used Python's timedelta for date math, which works with SQLite.
    # --- FIX: Changed date_created to result_datetime and result_value to value.
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recent_lab_results = LabResult.query.filter(
        LabResult.patient_id.in_(assigned_patient_ids), # More efficient query
        LabResult.result_datetime >= seven_days_ago
    ).order_by(LabResult.result_datetime.desc()).limit(5).all()
    lab_results_summary = [lab.to_dict() for lab in recent_lab_results]

    # 6. Active INPATIENT medication orders for assigned patients
    # --- FIX: Changed non-existent 'MedicationOrder' to the correct 'PatientMedication' model.
    # --- FIX: Changed is_active to status=='Active' and fixed field names.
    active_medications = PatientMedication.query.filter(
        PatientMedication.patient_id.in_(assigned_patient_ids),
        PatientMedication.status == 'Active',
        PatientMedication.type == 'INPATIENT_ACTIVE' # Assuming you only want to see inpatient meds
    ).order_by(PatientMedication.recorded_at.desc()).limit(10).all()
    medications_summary = [med.to_dict() for med in active_medications]

    # 7. Combine all data into a single response object
    dashboard_data = {
        "assigned_patients": patients_summary,
        "open_tasks": tasks_summary,
        "unread_notifications": {
            "count": unread_count,
            "items": notifications_summary
        },
        "upcoming_appointments": appointments_summary,
        "recent_lab_results": lab_results_summary,
        "active_medications": medications_summary
    }

    return jsonify(dashboard_data), 200