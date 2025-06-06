# hms_app_pkg/discharge/routes.py
from flask import Blueprint, request, jsonify, current_app, g
from .. import db
from ..models import DischargePlan, Patient, User # Ensure all necessary models are imported
from ..utils import permission_required # decode_access_token is used by permission_required in utils.py
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from datetime import datetime

discharge_bp = Blueprint('discharge_bp', __name__)

@discharge_bp.route('/patients/<string:patient_id>/discharge-plans', methods=['POST'])
@permission_required('discharge_plan:create')
def create_discharge_plan(patient_id):
    current_user = g.current_user
    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    anticipated_discharge_date_val = None
    if data.get('anticipated_discharge_date'):
        try:
            dt_str = data['anticipated_discharge_date']
            if not isinstance(dt_str, str):
                raise ValueError("Date must be a string in ISO format.")
            if 'T' not in dt_str: # If only date is provided, assume start of day (midnight UTC)
                dt_str += 'T00:00:00Z' # Explicitly UTC if no timezone info
            # Ensure to handle timezone-aware or naive datetime consistently with your DB
            anticipated_discharge_date_val = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except (ValueError, TypeError) as e:
            current_app.logger.error(f"Invalid date format for anticipated_discharge_date: {data.get('anticipated_discharge_date')}, Error: {e}")
            return jsonify({"error": "Invalid anticipated_discharge_date format. Use ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)."}), 400

    try:
        plan = DischargePlan(
            patient_id=patient.id,
            created_by_user_id=current_user.id,
            discharge_goals=data.get('discharge_goals'),
            followup_plan=data.get('followup_plan'),
            discharge_medications_summary=data.get('discharge_medications_summary'),
            discharge_needs=data.get('discharge_needs'),
            anticipated_discharge_date=anticipated_discharge_date_val,
            barriers_to_discharge=data.get('barriers_to_discharge'),
            family_or_caregiver_notes=data.get('family_or_caregiver_notes'),
            transportation_needs=data.get('transportation_needs'),
            home_environment_safety_notes=data.get('home_environment_safety_notes'),
            post_discharge_instructions=data.get('post_discharge_instructions'),
            equipment_needed=data.get('equipment_needed'),
            social_work_consult_ordered=data.get('social_work_consult_ordered', False),
            case_management_consult_ordered=data.get('case_management_consult_ordered', False),
            physical_therapy_consult_ordered=data.get('physical_therapy_consult_ordered', False),
            occupational_therapy_consult_ordered=data.get('occupational_therapy_consult_ordered', False),
            speech_therapy_consult_ordered=data.get('speech_therapy_consult_ordered', False),
            nutrition_consult_ordered=data.get('nutrition_consult_ordered', False),
            nursing_summary=data.get('nursing_summary'),
            therapy_summary=data.get('therapy_summary'),
            care_coordination_notes=data.get('care_coordination_notes')
        )
        db.session.add(plan)
        db.session.commit()
        return jsonify({"message": "Discharge plan created successfully.", "discharge_plan": plan.to_dict()}), 201
    except IntegrityError as e:
        db.session.rollback()
        current_app.logger.error(f"IntegrityError creating discharge plan: {e}")
        return jsonify({"error": "Could not create discharge plan. Ensure patient exists and data is valid."}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unexpected error creating discharge plan: {e}")
        return jsonify({"error": "An unexpected error occurred while creating the discharge plan."}), 500


@discharge_bp.route('/patients/<string:patient_id>/discharge-plans', methods=['GET'])
@permission_required('discharge_plan:read')
def get_discharge_plans_for_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    current_user = g.current_user

    # Authorization: Can user see plans for this patient?
    # This is a placeholder. Real logic might check if user is on care team,
    # or if they have 'discharge_plan:read:any' permission.
    # if not user_can_access_patient_data(current_user.id, patient_id) and \
    #    'discharge_plan:read:any' not in current_user.get_permissions():
    #     return jsonify({"error": "Unauthorized to view discharge plans for this patient."}), 403

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int) # Fewer plans usually displayed at once

    plans_pagination = DischargePlan.query.filter_by(patient_id=patient.id).order_by(DischargePlan.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        "discharge_plans": [plan.to_dict() for plan in plans_pagination.items],
        "total": plans_pagination.total,
        "page": plans_pagination.page,
        "per_page": plans_pagination.per_page,
        "pages": plans_pagination.pages
    }), 200

@discharge_bp.route('/discharge-plans/<string:plan_id>', methods=['GET'])
@permission_required('discharge_plan:read')
def get_discharge_plan(plan_id):
    plan = DischargePlan.query.get_or_404(plan_id)
    current_user = g.current_user
    # Add more specific authorization if needed (e.g., is user part of this patient's care team?)
    return jsonify(plan.to_dict())

@discharge_bp.route('/discharge-plans/<string:plan_id>', methods=['PUT'])
@permission_required('discharge_plan:update') # Base permission
def update_discharge_plan(plan_id):
    current_user = g.current_user
    plan = DischargePlan.query.get_or_404(plan_id)

    can_update_any = 'discharge_plan:update:any' in current_user.get_permissions()
    if plan.created_by_user_id != current_user.id and not can_update_any:
        return jsonify({"error": "Unauthorized: You are not the creator or lack general update privileges."}), 403

    data = request.get_json()
    if not data: 
        return jsonify({"error": "No update data provided"}), 400

    updatable_fields = [
        'discharge_goals', 'followup_plan', 'discharge_medications_summary', 'discharge_needs',
        'anticipated_discharge_date', 'barriers_to_discharge', 'family_or_caregiver_notes',
        'transportation_needs', 'home_environment_safety_notes', 'post_discharge_instructions',
        'equipment_needed', 'social_work_consult_ordered', 'case_management_consult_ordered',
        'physical_therapy_consult_ordered', 'occupational_therapy_consult_ordered',
        'speech_therapy_consult_ordered', 'nutrition_consult_ordered', 'nursing_summary',
        'therapy_summary', 'care_coordination_notes'
    ]
    for field in updatable_fields:
        if field in data:
            if field == 'anticipated_discharge_date':
                if data[field] is None:
                    setattr(plan, field, None)
                else:
                    try:
                        dt_str = data[field]
                        if not isinstance(dt_str, str): raise ValueError("Date must be string")
                        if 'T' not in dt_str: dt_str += 'T00:00:00Z'
                        setattr(plan, field, datetime.fromisoformat(dt_str.replace('Z', '+00:00')))
                    except (ValueError, TypeError) as e:
                        current_app.logger.error(f"Invalid date format for {field}: {data[field]}, Error: {e}")
                        return jsonify({"error": f"Invalid {field} format. Use ISO format."}), 400
            elif field.endswith('_ordered') and isinstance(data.get(field), bool):
                 setattr(plan, field, data[field])
            elif not field.endswith('_ordered'): # For text and other general fields
                setattr(plan, field, data.get(field))

    plan.updated_at = datetime.utcnow()
    try:
        db.session.commit()
        return jsonify({"message": "Discharge plan updated successfully.", "discharge_plan": plan.to_dict()})
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating discharge plan {plan_id}: {e}")
        return jsonify({"error": "Could not update discharge plan due to a database error."}), 400

@discharge_bp.route('/discharge-plans/<string:plan_id>/review', methods=['POST'])
@permission_required('discharge_plan:review')
def review_discharge_plan(plan_id):
    current_user = g.current_user
    plan = DischargePlan.query.get_or_404(plan_id)
    data = request.get_json()
    review_notes = data.get('review_notes') if data else "Reviewed"

    # Add logic for DischargePlan model to have review fields if needed
    # e.g., plan.reviewed_by_user_id = current_user.id
    # plan.reviewed_at = datetime.utcnow()
    # plan.review_notes = review_notes
    # For now, just a log message
    current_app.logger.info(f"Discharge plan {plan_id} reviewed by user {current_user.id}. Notes: {review_notes}")
    # db.session.commit() # If model fields were updated

    # This endpoint is a placeholder for more complex review logic.
    # It might involve changing a status on the plan or creating a separate review log entry.
    return jsonify({"message": "Discharge plan review recorded (placeholder).", "plan_id": plan.id}), 200


@discharge_bp.route('/discharge-plans/<string:plan_id>', methods=['DELETE'])
@permission_required('discharge_plan:delete') # Base permission
def delete_discharge_plan(plan_id):
    current_user = g.current_user
    plan = DischargePlan.query.get_or_404(plan_id)

    can_delete_any = 'discharge_plan:delete:any' in current_user.get_permissions()
    if plan.created_by_user_id != current_user.id and not can_delete_any:
        return jsonify({"error": "Unauthorized to delete this discharge plan."}), 403
        
    try:
        db.session.delete(plan)
        db.session.commit()
        return jsonify({"message": "Discharge plan deleted successfully."}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting discharge plan {plan_id}: {e}")
        return jsonify({"error": "Could not delete discharge plan due to a database error."}), 400
