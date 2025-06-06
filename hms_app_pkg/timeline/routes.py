# hms_app_pkg/timeline/routes.py
from flask import Blueprint, jsonify, g
from ..models import Patient, ClinicalNote, Order, LabResult, VitalSign, MedicationAdministration
from ..utils import permission_required
from datetime import datetime, timedelta

timeline_bp = Blueprint('timeline_bp', __name__)

@timeline_bp.route('/patients/<string:patient_id>/timeline', methods=['GET'])
@permission_required('patient:read:timeline') # We will add this permission next
def get_patient_timeline(patient_id):
    """
    Aggregates various patient events into a single chronological timeline.
    """
    # Ensure the patient exists
    Patient.query.get_or_404(patient_id)

    timeline_events = []

    # 1. Get Clinical Notes
    notes = ClinicalNote.query.filter_by(patient_id=patient_id).all()
    for note in notes:
        timeline_events.append({
            "event_type": "Clinical Note",
            "event_time": note.created_at,
            "summary": f"{note.note_type}: {note.title or 'Untitled'}",
            "details": {
                "note_id": note.id,
                "author_id": note.author_user_id,
                "status": note.status
            }
        })

    # 2. Get Orders
    orders = Order.query.filter_by(patient_id=patient_id).all()
    for order in orders:
        timeline_events.append({
            "event_type": "Order Placed",
            "event_time": order.order_placed_at,
            "summary": f"Order for '{order.orderable_item.name}' with status '{order.status}'",
            "details": {
                "order_id": order.id,
                "ordering_physician_id": order.ordering_physician_id,
                "priority": order.priority
            }
        })

    # 3. Get Lab Results
    lab_results = LabResult.query.filter_by(patient_id=patient_id).all()
    for lab in lab_results:
        timeline_events.append({
            "event_type": "Lab Result",
            "event_time": lab.result_datetime,
            "summary": f"Result for '{lab.test_name}': {lab.value} {lab.units or ''}",
            "details": {
                "lab_result_id": lab.id,
                "abnormal_flag": lab.abnormal_flag,
                "status": lab.status
            }
        })

    # 4. Get Medication Administrations from the MAR
    mar_entries = MedicationAdministration.query.filter_by(patient_id=patient_id).all()
    for entry in mar_entries:
        timeline_events.append({
            "event_type": "Medication Administration",
            "event_time": entry.administration_time,
            "summary": f"{entry.status}: '{entry.patient_medication.medication_name}'",
            "details": {
                "mar_id": entry.id,
                "administered_by_id": entry.administered_by_user_id,
                "dose_given": entry.dose_given
            }
        })

    # 5. Sort all collected events by time, newest first
    # We use a lambda function as the key to tell sorted() how to compare the dictionaries
    sorted_timeline = sorted(
        [event for event in timeline_events if event.get("event_time")], # Filter out any events with no timestamp
        key=lambda x: x['event_time'],
        reverse=True
    )

    # Convert datetime objects to strings for JSON compatibility
    for event in sorted_timeline:
        event['event_time'] = event['event_time'].isoformat()

    return jsonify(sorted_timeline)