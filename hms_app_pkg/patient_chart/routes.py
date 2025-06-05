# hms_app_pkg/patient_chart/routes.py
from flask import Blueprint, request, jsonify, current_app
from .. import db
from ..models import Patient, ClinicalNote, PatientAllergy # Add other relevant models like PatientProblemList
from ..utils import permission_required
import datetime

patient_chart_bp = Blueprint('patient_chart_bp', __name__)

# --- Patient Management Routes ---
@patient_chart_bp.route('/patients', methods=['POST'])
@permission_required('patient:create')
def create_patient(): # current_user_id is implicitly available if decorator adds it to g or similar
    # If permission_required decorator is modified to pass current_user_id as kwarg:
    # def create_patient(current_user_id):
    data = request.get_json()
    required_fields = ['mrn', 'first_name', 'last_name', 'date_of_birth']
    if not all(field in data for field in required_fields):
        return jsonify({"message": "Missing required fields (mrn, first_name, last_name, date_of_birth)"}), 400
    
    if Patient.query.filter_by(mrn=data['mrn']).first():
        return jsonify({"message": f"Patient with MRN {data['mrn']} already exists."}), 409

    try:
        # Ensure date_of_birth is a string in 'YYYY-MM-DD' format from the client
        dob_str = data['date_of_birth']
        dob = datetime.datetime.strptime(dob_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return jsonify({"message": "Invalid date_of_birth format or type. Use YYYY-MM-DD string."}), 400

    new_patient = Patient(
        mrn=data['mrn'],
        first_name=data['first_name'],
        last_name=data['last_name'],
        date_of_birth=dob,
        gender=data.get('gender'),
        attending_physician_id=data.get('attending_physician_id'), # Should be validated
        code_status=data.get('code_status', 'Full Code')
    )
    db.session.add(new_patient)
    db.session.commit()
    return jsonify({"message": "Patient created successfully", "patient_id": new_patient.id}), 201

@patient_chart_bp.route('/patients/<string:patient_identifier>/header-details', methods=['GET'])
@permission_required('patient:read')
def get_patient_header(patient_identifier): # current_user_id from decorator if needed
    patient = Patient.query.filter((Patient.mrn == patient_identifier) | (Patient.id == patient_identifier)).first()
    if not patient:
        return jsonify({"message": "Patient not found"}), 404
    
    allergies_summary = [a.allergen_name for a in patient.allergies if a.is_active]
    age = None
    if patient.date_of_birth:
        today = datetime.date.today()
        age = today.year - patient.date_of_birth.year - ((today.month, today.day) < (patient.date_of_birth.month, patient.date_of_birth.day))


    return jsonify({
        "patient_id": patient.id,
        "mrn": patient.mrn,
        "full_name": f"{patient.first_name} {patient.last_name}",
        "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
        "age": age,
        "gender": patient.gender,
        "attending_physician_id": patient.attending_physician_id,
        "code_status": patient.code_status,
        "allergies_summary": allergies_summary[:3]
    }), 200

# --- Clinical Documentation Routes ---
@patient_chart_bp.route('/patients/<string:patient_id>/notes', methods=['POST'])
@permission_required('note:create')
def create_clinical_note(patient_id): # current_user_id from decorator
    # To get current_user_id if decorator doesn't pass it as kwarg:
    # auth_header = request.headers.get('Authorization')
    # token = auth_header.split(" ")[1] if auth_header else None
    # payload = decode_access_token(token) # Assuming decode_access_token is in utils
    # current_user_id = payload.get('sub') if isinstance(payload, dict) else None
    # if not current_user_id: return jsonify({"message":"Authentication error"}), 401
    # For this example, assuming decorator handles getting current_user_id if needed by the logic below

    # A more robust way to get current_user_id if decorator stores it in flask.g
    # from flask import g
    # current_user_id = g.get('user_id', None) # Or whatever key you use
    # if not current_user_id: # Fallback if not in g, or handle error
    #     # This part depends on how your decorator makes current_user_id available
    #     # For simplicity, let's assume it's passed if the route function declares it
    #     # If not, you'd fetch it from the token as shown above, or your decorator must provide it
    #     # This example will assume the decorator makes it available if the function argument exists
    #     # or the logic below doesn't strictly need it beyond permission check.
    #     # If current_user_id is needed for author_user_id, it MUST be reliably obtained.
    #
    # Let's assume `permission_required` decorator in `utils.py` is modified to add `current_user_id` to `kwargs`
    # So, the function signature would be `def create_clinical_note(patient_id, current_user_id):`
    # For now, I'll proceed assuming current_user_id for authorship needs to be explicitly fetched if not passed.
    # The `permission_required` in the provided utils.py passes `current_user_id` as a kwarg.
    # So the signature should be: def create_clinical_note(patient_id, current_user_id):
    # However, Flask route parameters (like patient_id) are passed as positional args first.
    # The decorator's kwarg will be available if the function signature accepts it.
    # Let's adjust the decorator or how we retrieve user_id.
    # For now, let's assume the decorator makes current_user_id available through flask.g or similar,
    # or the route will be adjusted.
    # The provided utils.py `permission_required` adds `kwargs['current_user_id'] = user_id`.
    # So the route function should be `def create_clinical_note(patient_id, current_user_id):`
    # However, `patient_id` is a URL variable.
    # Let's assume the decorator logic is robust.
    # For the `author_user_id`, we need the actual ID.
    # The `permission_required` decorator in the previous `utils.py` example adds `current_user_id` to `kwargs`.
    # So the function signature should be:
    # def create_clinical_note(patient_id, **kwargs):
    #    current_user_id = kwargs.get('current_user_id')
    # This is a common pattern. Let's use this.

    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1] if auth_header and auth_header.startswith('Bearer ') else None
    if not token: return jsonify({"message": "Auth token not found"}), 401
    
    from ..utils import decode_access_token # Import locally if not already at top
    payload = decode_access_token(token)
    if isinstance(payload, str) or not payload.get('sub'): # Error or no user_id
        return jsonify({"message": "Invalid token or user ID missing"}), 401
    current_user_id_from_token = payload['sub']


    data = request.get_json()
    patient = Patient.query.get(patient_id)
    if not patient: return jsonify({"message": "Patient not found"}), 404
    if not data or not data.get('note_type') or not data.get('content_text'):
        return jsonify({"message": "note_type and content_text are required"}), 400

    new_note = ClinicalNote(
        patient_id=patient_id,
        author_user_id=current_user_id_from_token, # Use ID from token
        note_type=data['note_type'],
        service_specialty=data.get('service_specialty'),
        title=data.get('title'),
        content_text=data['content_text'],
        status='Draft'
    )
    db.session.add(new_note)
    db.session.commit()
    return jsonify({"message": "Note created successfully", "note_id": new_note.id}), 201

@patient_chart_bp.route('/patients/<string:patient_id>/notes', methods=['GET'])
@permission_required('note:read')
def get_patient_notes(patient_id): # current_user_id from decorator if needed for filtering
    patient = Patient.query.get(patient_id)
    if not patient: return jsonify({"message": "Patient not found"}), 404
    
    notes_query = ClinicalNote.query.filter_by(patient_id=patient_id)
    # Add filters from request.args (type, status, date_range, etc.)
    # status_filter = request.args.get('status')
    # if status_filter:
    #     notes_query = notes_query.filter_by(status=status_filter)
    
    notes_data = [{
        "note_id": note.id, "note_type": note.note_type, "title": note.title,
        "author_user_id": note.author_user_id, "status": note.status,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        "signed_at": note.signed_at.isoformat() if note.signed_at else None,
    } for note in notes_query.order_by(ClinicalNote.created_at.desc()).all()]
    return jsonify(notes_data), 200

@patient_chart_bp.route('/notes/<string:note_id>/sign', methods=['POST'])
@permission_required('note:sign')
def sign_clinical_note(note_id): # current_user_id from decorator
    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1] if auth_header and auth_header.startswith('Bearer ') else None
    if not token: return jsonify({"message": "Auth token not found"}), 401
    
    from ..utils import decode_access_token
    payload = decode_access_token(token)
    if isinstance(payload, str) or not payload.get('sub'):
        return jsonify({"message": "Invalid token or user ID missing"}), 401
    current_user_id_from_token = payload['sub']

    note = ClinicalNote.query.get(note_id)
    if not note: return jsonify({"message": "Note not found"}), 404
    if note.status == 'Final': return jsonify({"message": "Note is already signed"}), 400
    
    # Simplified signing logic: only author can sign, or specific co-sign logic needed
    if note.author_user_id != current_user_id_from_token:
         # Add more complex co-signing permission check here if needed
         return jsonify({"message": "Unauthorized to sign this note (only author can sign in this basic setup)"}), 403

    note.status = 'Final'
    note.signed_at = datetime.datetime.utcnow()
    note.signed_by_user_id = current_user_id_from_token
    db.session.commit()
    return jsonify({"message": "Note signed successfully", "note_id": note.id}), 200

# Add other patient_chart related routes here (e.g., for problems, allergies)
