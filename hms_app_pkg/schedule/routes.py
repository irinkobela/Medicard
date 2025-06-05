# hms_app_pkg/schedule/routes.py
from flask import Blueprint, request, jsonify, current_app, g
from .. import db
from ..models import Appointment, Patient, User
from ..utils import permission_required
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload # <<< ADD THIS IMPORT

schedule_bp = Blueprint('schedule_bp', __name__)

CANCELLED_STATUSES = ['CancelledByPatient', 'CancelledByClinic', 'NoShow']

def parse_iso_datetime(dt_str):
    """Helper: Parse ISO string, returns None on failure."""
    if not dt_str or not isinstance(dt_str, str): # Added check for None or non-string
        return None
    try:
        return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        current_app.logger.warning(f"Invalid datetime format for string: {dt_str}")
        return None

def check_appointment_conflict(provider_user_id, start_dt, end_dt, exclude_appointment_id=None):
    """Helper: Checks for overlapping appointments for a given provider."""
    if not all([provider_user_id, start_dt, end_dt]):
        return None 

    query = Appointment.query.filter(
        Appointment.provider_user_id == provider_user_id,
        Appointment.status.notin_(CANCELLED_STATUSES),
        Appointment.start_datetime < end_dt,
        Appointment.end_datetime > start_dt
    )
    if exclude_appointment_id:
        query = query.filter(Appointment.id != exclude_appointment_id)
    return query.first()

@schedule_bp.before_request
def ensure_json():
    if request.method in ['POST', 'PUT', 'PATCH'] and not request.is_json:
        return jsonify({"error": "Request body must be JSON."}), 415

@schedule_bp.route('/appointments', methods=['POST'])
@permission_required('appointment:create')
def create_appointment():
    current_user = g.current_user
    data = request.get_json() 
    required_fields = ['patient_id', 'provider_user_id', 'start_datetime', 'end_datetime']
    missing = [f for f in required_fields if f not in data or not data[f]]
    if missing:
        return jsonify({"error": f"Missing or empty required fields: {', '.join(missing)}"}), 400

    patient = Patient.query.get(data['patient_id'])
    if not patient: return jsonify({"error": "Patient not found."}), 404
    provider = User.query.get(data['provider_user_id'])
    if not provider: return jsonify({"error": "Provider not found."}), 404

    start_dt = parse_iso_datetime(data['start_datetime'])
    end_dt = parse_iso_datetime(data['end_datetime'])
    if not start_dt or not end_dt or end_dt <= start_dt:
        return jsonify({"error": "Invalid or inconsistent start/end datetime. Ensure ISO format and end is after start."}), 400

    if check_appointment_conflict(provider.id, start_dt, end_dt):
        return jsonify({"error": "Provider has a conflicting appointment in the selected time slot."}), 409

    try:
        new_appointment = Appointment(
            patient_id=patient.id,
            provider_user_id=provider.id,
            start_datetime=start_dt,
            end_datetime=end_dt,
            appointment_type=data.get('appointment_type'),
            status=data.get('status', 'Scheduled'),
            location=data.get('location'),
            reason_for_visit=data.get('reason_for_visit'),
            notes=data.get('notes'),
            created_by_user_id=current_user.id
        )
        db.session.add(new_appointment)
        db.session.commit()
        return jsonify({"message": "Appointment created successfully.", "appointment": new_appointment.to_dict(include_related=True)}), 201
    except IntegrityError:
        db.session.rollback()
        current_app.logger.error("IntegrityError creating appointment.")
        return jsonify({"error": "Database integrity error creating appointment."}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating appointment: {e}")
        return jsonify({"error": "Unexpected error occurred while creating appointment."}), 500

@schedule_bp.route('/appointments', methods=['GET'])
@permission_required('appointment:read')
def get_appointments():
    current_user = g.current_user
    user_permissions = g.token_permissions
    can_read_any = 'appointment:read:any' in user_permissions

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = Appointment.query.options(
        joinedload(Appointment.patient), 
        joinedload(Appointment.provider),
        joinedload(Appointment.created_by)
    )

    patient_id_filter = request.args.get('patient_id')
    provider_id_filter = request.args.get('provider_user_id')
    start_date_query_str = request.args.get('start_date')
    end_date_query_str = request.args.get('end_date')
    status_filter = request.args.get('status')
    appointment_type_filter = request.args.get('type')

    if not can_read_any:
        query = query.filter(Appointment.provider_user_id == current_user.id)

    if patient_id_filter:
        if not can_read_any and (not provider_id_filter or int(provider_id_filter) != current_user.id):
            query = query.filter(Appointment.patient_id == patient_id_filter, Appointment.provider_user_id == current_user.id)
        else:
            query = query.filter_by(patient_id=patient_id_filter)

    if provider_id_filter:
        try:
            prov_id_int = int(provider_id_filter)
            if not can_read_any and prov_id_int != current_user.id:
                return jsonify({"error": "Unauthorized to view appointments for other providers."}), 403
            query = query.filter_by(provider_user_id=prov_id_int)
        except ValueError:
            return jsonify({"error": "Invalid provider_user_id format."}), 400


    if start_date_query_str:
        start_dt = parse_iso_datetime(start_date_query_str)
        if not start_dt: return jsonify({"error": "Invalid start_date filter format."}), 400
        query = query.filter(Appointment.start_datetime >= start_dt)
    
    if end_date_query_str:
        end_dt = parse_iso_datetime(end_date_query_str)
        if not end_dt: return jsonify({"error": "Invalid end_date filter format."}), 400
        if 'T' not in end_date_query_str: # If only date, make it end of day
            end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        query = query.filter(Appointment.start_datetime <= end_dt)

    if status_filter:
        query = query.filter(Appointment.status.ilike(f'%{status_filter}%'))
    if appointment_type_filter:
        query = query.filter(Appointment.appointment_type.ilike(f'%{appointment_type_filter}%'))

    appointments_pagination = query.order_by(Appointment.start_datetime.asc()).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "appointments": [a.to_dict(include_related=True) for a in appointments_pagination.items],
        "page": appointments_pagination.page,
        "total": appointments_pagination.total,
        "pages": appointments_pagination.pages,
        "per_page": appointments_pagination.per_page
    }), 200


@schedule_bp.route('/appointments/<string:appointment_id>', methods=['GET'])
@permission_required('appointment:read')
def get_appointment(appointment_id):
    appointment = Appointment.query.options(
        joinedload(Appointment.patient), 
        joinedload(Appointment.provider),
        joinedload(Appointment.created_by)
    ).get_or_404(appointment_id)
    
    current_user = g.current_user
    user_permissions = g.token_permissions
    can_read_any = 'appointment:read:any' in user_permissions
    
    if not (appointment.provider_user_id == current_user.id or \
            appointment.created_by_user_id == current_user.id or \
            can_read_any ):
        return jsonify({"error": "Unauthorized to view this appointment."}), 403
            
    return jsonify(appointment.to_dict(include_related=True))


@schedule_bp.route('/appointments/<string:appointment_id>', methods=['PUT'])
@permission_required('appointment:update')
def update_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    current_user = g.current_user
    user_permissions = g.token_permissions
    data = request.get_json()
    if not data: return jsonify({"error": "No update data provided."}), 400

    can_update_any = 'appointment:update:any' in user_permissions
    if not (appointment.created_by_user_id == current_user.id or \
            appointment.provider_user_id == current_user.id or \
            can_update_any):
        return jsonify({"error": "Unauthorized to update this appointment."}), 403

    new_start_dt_str = data.get('start_datetime')
    new_end_dt_str = data.get('end_datetime')
    new_provider_id = data.get('provider_user_id')

    check_start_dt = parse_iso_datetime(new_start_dt_str) if new_start_dt_str else appointment.start_datetime
    check_end_dt = parse_iso_datetime(new_end_dt_str) if new_end_dt_str else appointment.end_datetime
    check_provider_id = new_provider_id if new_provider_id is not None else appointment.provider_user_id
    
    if not User.query.get(check_provider_id): # Validate new or existing provider ID
        return jsonify({"error": "Provider user ID for conflict check not found."}), 404

    if not check_start_dt or not check_end_dt or check_end_dt <= check_start_dt:
        return jsonify({"error": "Invalid or inconsistent start/end datetime for update."}), 400

    if (new_start_dt_str or new_end_dt_str or new_provider_id is not None):
        if check_appointment_conflict(check_provider_id, check_start_dt, check_end_dt, exclude_appointment_id=appointment.id):
            return jsonify({"error": "Proposed change conflicts with another appointment for the provider."}), 409
    
    if new_start_dt_str: appointment.start_datetime = check_start_dt
    if new_end_dt_str: appointment.end_datetime = check_end_dt
    if new_provider_id is not None: appointment.provider_user_id = new_provider_id
        
    for field in ['appointment_type', 'status', 'location', 'reason_for_visit', 'notes']:
        if field in data:
            setattr(appointment, field, data[field])
            
    appointment.updated_at = datetime.utcnow()
    try:
        db.session.commit()
        return jsonify({"message": "Appointment updated successfully.", "appointment": appointment.to_dict(include_related=True)})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating appointment {appointment_id}: {e}")
        return jsonify({"error": "Could not update appointment."}), 500

@schedule_bp.route('/appointments/<string:appointment_id>/cancel', methods=['POST'])
@permission_required('appointment:cancel')
def cancel_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    current_user = g.current_user
    user_permissions = g.token_permissions
    data = request.get_json() or {}
    cancel_reason = data.get('reason', 'Cancelled by user action.')

    can_cancel_any = 'appointment:cancel:any' in user_permissions
    if not (appointment.created_by_user_id == current_user.id or \
            appointment.provider_user_id == current_user.id or \
            can_cancel_any):
        return jsonify({"error": "Unauthorized to cancel this appointment."}), 403

    if appointment.status in CANCELLED_STATUSES:
        return jsonify({"message": "Appointment already cancelled.", "appointment": appointment.to_dict(include_related=True)}), 400

    appointment.status = 'CancelledByClinic' # Default, adjust if patient role is identified
    appointment.notes = f"[CANCELLED on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}] Reason: {cancel_reason}\n---\n{appointment.notes or ''}".strip()
    appointment.updated_at = datetime.utcnow()

    try:
        db.session.commit()
        return jsonify({"message": f"Appointment cancelled successfully ({appointment.status}).", "appointment": appointment.to_dict(include_related=True)})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error cancelling appointment {appointment_id}: {e}")
        return jsonify({"error": "Could not cancel appointment."}), 500
