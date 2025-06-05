from flask import Blueprint, request, jsonify, current_app, g
from .. import db  # Corrected: Import db from the parent package __init__
from ..models import VitalSign, Patient, User # Corrected: Import models from parent package
from ..utils import permission_required, decode_access_token # Corrected: Import utils from parent package
from datetime import datetime, date
from sqlalchemy.exc import IntegrityError
import math

vitalsigns_bp = Blueprint('vitalsigns', __name__)

def calculate_bmi_util(weight_kg, height_cm):
    if weight_kg and height_cm and height_cm > 0:
        height_m = height_cm / 100.0
        return round(weight_kg / (height_m ** 2), 2)
    return None

def calculate_news2_util(vitals_dict): # Takes a dictionary of vital signs
    score = 0
    hr = vitals_dict.get('heart_rate_bpm')
    rr = vitals_dict.get('respiratory_rate_rpm')
    spo2 = vitals_dict.get('oxygen_saturation_percent')
    temp = vitals_dict.get('temperature_celsius')
    sys_bp = vitals_dict.get('systolic_bp_mmhg')
    consciousness = vitals_dict.get('consciousness_level', 'alert').lower()

    if rr is not None:
        if rr <= 8: score += 3
        elif 9 <= rr <= 11: score += 1
        elif 21 <= rr <= 24: score += 2
        elif rr >= 25: score += 3
    if spo2 is not None:
        if spo2 <= 91: score += 3
        elif 92 <= spo2 <= 93: score += 2
        elif 94 <= spo2 <= 95: score += 1
    if temp is not None:
        if temp <= 35.0: score += 3
        elif 35.1 <= temp <= 36.0: score += 1
        elif 38.1 <= temp <= 39.0: score += 1
        elif temp >= 39.1: score += 2
    if sys_bp is not None:
        if sys_bp <= 90: score += 3
        elif 91 <= sys_bp <= 100: score += 2
        elif 101 <= sys_bp <= 110: score += 1
        elif sys_bp >= 220: score += 3
    if hr is not None:
        if hr <= 40: score += 3
        elif 41 <= hr <= 50: score += 1
        elif 91 <= hr <= 110: score += 1
        elif 111 <= hr <= 130: score += 2
        elif hr >= 131: score += 3
    if consciousness not in ['alert', 'a (alert)']:
        score += 3
    return score


@vitalsigns_bp.route('/patients/<string:patient_id>/vitals', methods=['POST'])
@permission_required('vitals:record')
def create_vital(patient_id): # Renamed from record_vital_signs
    current_user = g.current_user # Use g.current_user from upgraded utils.py

    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json()
    if not data:
        return jsonify({"message": "No data provided."}), 400

    recorded_at_val = datetime.utcnow()
    if data.get('recorded_at'):
        try:
            recorded_at_str = data['recorded_at']
            if '.' in recorded_at_str:
                recorded_at_val = datetime.strptime(recorded_at_str, '%Y-%m-%dT%H:%M:%S.%f')
            else:
                recorded_at_val = datetime.strptime(recorded_at_str, '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            return jsonify({"message": "Invalid recorded_at format. Use ISO format."}), 400

    def get_numeric(key, data_type=float): # Local helper for this route
        val = data.get(key)
        if val is not None:
            try: return data_type(val)
            except (ValueError, TypeError): return None
        return None

    try:
        new_vitals = VitalSign(
            patient_id=patient.id,
            recorded_by_user_id=current_user.id, # Use current_user from g
            recorded_at=recorded_at_val,
            temperature_celsius=get_numeric('temperature_celsius'),
            heart_rate_bpm=get_numeric('heart_rate_bpm', int),
            respiratory_rate_rpm=get_numeric('respiratory_rate_rpm', int),
            systolic_bp_mmhg=get_numeric('systolic_bp_mmhg', int),
            diastolic_bp_mmhg=get_numeric('diastolic_bp_mmhg', int),
            oxygen_saturation_percent=get_numeric('oxygen_saturation_percent'),
            pain_score_0_10=get_numeric('pain_score_0_10', int),
            weight_kg=get_numeric('weight_kg'),
            height_cm=get_numeric('height_cm'),
            blood_glucose_mg_dl=get_numeric('blood_glucose_mg_dl', int),
            blood_glucose_mmol_l=get_numeric('blood_glucose_mmol_l'),
            blood_glucose_type=data.get('blood_glucose_type'),
            consciousness_level=data.get('consciousness_level'),
            patient_position=data.get('patient_position'),
            activity_level=data.get('activity_level'),
            o2_therapy_device=data.get('o2_therapy_device'),
            o2_flow_rate_lpm=get_numeric('o2_flow_rate_lpm'),
            fio2_percent=get_numeric('fio2_percent'),
            troponin_ng_l=get_numeric('troponin_ng_l'),
            creatinine_umol_l=get_numeric('creatinine_umol_l'),
            ecg_changes=data.get('ecg_changes'),
            notes=data.get('notes')
        )
        db.session.add(new_vitals)
        db.session.commit()
        return jsonify(new_vitals.to_dict()), 201 # Use to_dict() from model
    except IntegrityError as e:
        db.session.rollback()
        current_app.logger.error(f"Integrity error creating vital: {e}")
        return jsonify({"message": "Error saving vital signs. Check data integrity."}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unexpected error creating vital: {e}")
        return jsonify({"message": "An unexpected error occurred."}), 500

@vitalsigns_bp.route('/patients/<string:patient_id>/vitals', methods=['GET'])
@permission_required('vitals:read')
def get_all_vitals_for_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    # Add authorization checks if needed, beyond the basic permission

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 30, type=int)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    query = VitalSign.query.filter_by(patient_id=patient.id)
    if start_date_str:
        try:
            query = query.filter(VitalSign.recorded_at >= datetime.fromisoformat(start_date_str.replace('Z', '+00:00')))
        except ValueError: return jsonify({"message": "Invalid start_date format."}), 400
    if end_date_str:
        try:
            query = query.filter(VitalSign.recorded_at <= datetime.fromisoformat(end_date_str.replace('Z', '+00:00')))
        except ValueError: return jsonify({"message": "Invalid end_date format."}), 400

    vitals_pagination = query.order_by(VitalSign.recorded_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "vitals": [v.to_dict() for v in vitals_pagination.items],
        "total": vitals_pagination.total, "page": vitals_pagination.page,
        "per_page": vitals_pagination.per_page, "pages": vitals_pagination.pages
    }), 200

@vitalsigns_bp.route('/vitals/<string:vital_id>', methods=['GET'])
@permission_required('vitals:read')
def get_vital(vital_id): # Renamed from get_specific_vitals_entry for consistency
    vital = VitalSign.query.get_or_404(vital_id)
    # Add authorization logic: Can g.current_user view this vital (e.g. based on patient access)?
    return jsonify(vital.to_dict())

@vitalsigns_bp.route('/vitals/<string:vital_id>', methods=['PUT'])
@permission_required('vitals:update')
def update_vital(vital_id):
    current_user = g.current_user
    vital = VitalSign.query.get_or_404(vital_id)

    # Authorization: e.g., only user who recorded or admin/supervisor with 'vitals:update:any'
    can_update_any = 'vitals:update:any' in current_user.get_permissions() # Add this perm if needed
    if not (vital.recorded_by_user_id == current_user.id or can_update_any):
        return jsonify({"message": "Unauthorized to update this vital signs entry."}), 403
    
    data = request.get_json()
    if not data: return jsonify({"message": "No update data provided."}), 400

    # Explicitly update fields to prevent mass assignment vulnerabilities
    # and allow for type checking/conversion if necessary.
    # This example assumes all fields in VitalSign.to_dict() (excluding read-only like id, patient_id)
    # could potentially be updated if present in `data`.
    
    def get_numeric(key, data_type=float): # Local helper for this route
        val = data.get(key)
        if val is not None: # Check if key is in data to allow sending null to clear a value
            try: return data_type(val) if val is not None else None # Ensure None is handled if value is explicitly null
            except (ValueError, TypeError): return None # Or return current value: vital.__getattribute__(key)
        return None # If key not in data, don't change existing value

    if 'recorded_at' in data:
        try: vital.recorded_at = datetime.fromisoformat(data['recorded_at'].replace('Z', '+00:00'))
        except (ValueError, TypeError): return jsonify({"message": "Invalid recorded_at format."}), 400
    
    vital.temperature_celsius = get_numeric('temperature_celsius') if 'temperature_celsius' in data else vital.temperature_celsius
    vital.heart_rate_bpm = get_numeric('heart_rate_bpm', int) if 'heart_rate_bpm' in data else vital.heart_rate_bpm
    vital.respiratory_rate_rpm = get_numeric('respiratory_rate_rpm', int) if 'respiratory_rate_rpm' in data else vital.respiratory_rate_rpm
    vital.systolic_bp_mmhg = get_numeric('systolic_bp_mmhg', int) if 'systolic_bp_mmhg' in data else vital.systolic_bp_mmhg
    vital.diastolic_bp_mmhg = get_numeric('diastolic_bp_mmhg', int) if 'diastolic_bp_mmhg' in data else vital.diastolic_bp_mmhg
    vital.oxygen_saturation_percent = get_numeric('oxygen_saturation_percent') if 'oxygen_saturation_percent' in data else vital.oxygen_saturation_percent
    vital.pain_score_0_10 = get_numeric('pain_score_0_10', int) if 'pain_score_0_10' in data else vital.pain_score_0_10
    vital.weight_kg = get_numeric('weight_kg') if 'weight_kg' in data else vital.weight_kg
    vital.height_cm = get_numeric('height_cm') if 'height_cm' in data else vital.height_cm
    vital.blood_glucose_mg_dl = get_numeric('blood_glucose_mg_dl', int) if 'blood_glucose_mg_dl' in data else vital.blood_glucose_mg_dl
    vital.blood_glucose_mmol_l = get_numeric('blood_glucose_mmol_l') if 'blood_glucose_mmol_l' in data else vital.blood_glucose_mmol_l
    vital.blood_glucose_type = data.get('blood_glucose_type', vital.blood_glucose_type)
    vital.consciousness_level = data.get('consciousness_level', vital.consciousness_level)
    vital.patient_position = data.get('patient_position', vital.patient_position)
    vital.activity_level = data.get('activity_level', vital.activity_level)
    vital.o2_therapy_device = data.get('o2_therapy_device', vital.o2_therapy_device)
    vital.o2_flow_rate_lpm = get_numeric('o2_flow_rate_lpm') if 'o2_flow_rate_lpm' in data else vital.o2_flow_rate_lpm
    vital.fio2_percent = get_numeric('fio2_percent') if 'fio2_percent' in data else vital.fio2_percent
    vital.troponin_ng_l = get_numeric('troponin_ng_l') if 'troponin_ng_l' in data else vital.troponin_ng_l
    vital.creatinine_umol_l = get_numeric('creatinine_umol_l') if 'creatinine_umol_l' in data else vital.creatinine_umol_l
    vital.ecg_changes = data.get('ecg_changes', vital.ecg_changes)
    vital.notes = data.get('notes', vital.notes)
    
    try:
        db.session.commit()
        return jsonify(vital.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating vital {vital_id}: {e}")
        return jsonify({"message": "Error updating vital signs."}), 500

@vitalsigns_bp.route('/vitals/<string:vital_id>', methods=['DELETE'])
@permission_required('vitals:delete')
def delete_vital(vital_id):
    current_user = g.current_user
    vital = VitalSign.query.get_or_404(vital_id)

    # Authorization: e.g., only user who recorded or admin/supervisor with 'vitals:delete:any'
    can_delete_any = 'vitals:delete:any' in current_user.get_permissions()
    if not (vital.recorded_by_user_id == current_user.id or can_delete_any):
        return jsonify({"message": "Unauthorized to delete this vital signs entry."}), 403

    db.session.delete(vital)
    db.session.commit()
    return '', 204

@vitalsigns_bp.route('/patients/<string:patient_id>/vitals/derived-scores/latest', methods=['GET'])
@permission_required('vitals:read:derived_scores')
def get_derived_scores_for_patient_latest_vitals(patient_id): # Renamed for clarity
    patient = Patient.query.get_or_404(patient_id)
    latest_vital = VitalSign.query.filter_by(patient_id=patient.id).order_by(VitalSign.recorded_at.desc()).first()
    if not latest_vital:
        return jsonify({"message": "No vital signs found for this patient to calculate scores."}), 404
    
    # The to_dict() method in the VitalSign model should now include all calculated scores
    # because they are @property methods.
    return jsonify(latest_vital.to_dict()), 200
