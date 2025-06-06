# hms_app_pkg/reports/routes.py
from flask import Blueprint, request, jsonify, current_app, g
from .. import db
from ..models import Patient, Appointment, User, LabResult, Task 
# Assuming 'Medication' model will be created for medication_usage_report,
# or PatientMedication will be adapted.
# from ..models import Medication 
from ..utils import permission_required
from datetime import datetime, date, timedelta
from collections import Counter
from sqlalchemy import func, cast, Date as SQLDate # For casting datetime to date

reports_bp = Blueprint('reports_bp', __name__)

@reports_bp.route('/reports/patient-demographics', methods=['GET'])
@permission_required('report:read:patient_demographics')
def patient_demographics_report():
    current_user = g.current_user 
    try:
        gender_distribution_query = db.session.query(
            Patient.gender,
            func.count(Patient.id).label('count')
        ).group_by(Patient.gender).all()
        gender_distribution = {gender: count for gender, count in gender_distribution_query if gender}

        patients = Patient.query.all() # For larger DBs, this is inefficient for age calculation
        age_groups = {"0-17": 0, "18-35": 0, "36-50": 0, "51-65": 0, "66+": 0, "Unknown": 0}
        today = date.today()
        for patient in patients:
            if patient.date_of_birth:
                age = today.year - patient.date_of_birth.year - \
                      ((today.month, today.day) < (patient.date_of_birth.month, patient.date_of_birth.day))
                if 0 <= age <= 17: age_groups["0-17"] += 1
                elif 18 <= age <= 35: age_groups["18-35"] += 1
                elif 36 <= age <= 50: age_groups["36-50"] += 1
                elif 51 <= age <= 65: age_groups["51-65"] += 1
                elif age >= 66: age_groups["66+"] += 1
                else: age_groups["Unknown"] +=1 
            else:
                age_groups["Unknown"] += 1
        
        report_data = {
            "report_name": "Patient Demographics Summary",
            "generated_at": datetime.utcnow().isoformat(),
            "total_patients": len(patients),
            "gender_distribution": gender_distribution,
            "age_group_distribution": age_groups
        }
        return jsonify(report_data), 200
    except Exception as e:
        current_app.logger.error(f"Error generating patient demographics report: {e}")
        return jsonify({"error": "Could not generate patient demographics report."}), 500

@reports_bp.route('/reports/appointment-statistics', methods=['GET'])
@permission_required('report:read:appointment_stats')
def appointment_statistics_report():
    current_user = g.current_user
    try:
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        provider_id_filter = request.args.get('provider_id')
        appointment_type_filter = request.args.get('appointment_type')

        if not start_date_str or not end_date_str:
            return jsonify({"error": "start_date and end_date query parameters are required (YYYY-MM-DD)."}), 400
        try:
            start_datetime = datetime.strptime(start_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
            end_datetime = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=999999)
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400
        if end_datetime < start_datetime:
            return jsonify({"error": "end_date must be after start_date."}), 400

        query = Appointment.query.filter(
            Appointment.start_datetime >= start_datetime,
            Appointment.start_datetime <= end_datetime
        )
        if provider_id_filter:
            query = query.filter_by(provider_user_id=provider_id_filter)
        if appointment_type_filter:
            query = query.filter(Appointment.appointment_type.ilike(f'%{appointment_type_filter}%'))

        appointments_in_range = query.all()
        status_counts = Counter(apt.status for apt in appointments_in_range)
        type_counts = Counter(apt.appointment_type for apt in appointments_in_range if apt.appointment_type)
        
        provider_counts = {}
        if not provider_id_filter:
            provider_query = db.session.query(
                Appointment.provider_user_id, User.full_name, func.count(Appointment.id).label('count')
            ).join(User, User.id == Appointment.provider_user_id).filter(
                Appointment.start_datetime >= start_datetime, Appointment.start_datetime <= end_datetime
            )
            if appointment_type_filter:
                 provider_query = provider_query.filter(Appointment.appointment_type.ilike(f'%{appointment_type_filter}%'))
            provider_appts = provider_query.group_by(Appointment.provider_user_id, User.full_name).all()
            provider_counts = { (name or f"Provider ID {pid}") : count for pid, name, count in provider_appts}

        report_data = {
            "report_name": "Appointment Statistics",
            "period_start": start_datetime.isoformat(), "period_end": end_datetime.isoformat(),
            "generated_at": datetime.utcnow().isoformat(),
            "total_appointments_in_period": len(appointments_in_range),
            "appointments_by_status": dict(status_counts),
            "appointments_by_type": dict(type_counts),
            "appointments_by_provider": provider_counts if not provider_id_filter else "Filtered by specific provider"
        }
        return jsonify(report_data), 200
    except Exception as e:
        current_app.logger.error(f"Error generating appointment statistics report: {e}")
        return jsonify({"error": "Could not generate appointment statistics report."}), 500

@reports_bp.route('/reports/lab-result-trends', methods=['GET'])
@permission_required('report:read:lab_result_trends')
def lab_result_trends_report():
    try:
        test_name = request.args.get('test_name')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        patient_id_filter = request.args.get('patient_id') # Optional: filter by patient

        if not start_date_str or not end_date_str:
            return jsonify({"error": "start_date and end_date are required (YYYY-MM-DD)"}), 400
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() # Compare dates
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({"error": "Invalid date format for start_date/end_date. Use YYYY-MM-DD."}), 400

        query = db.session.query(
            func.date(LabResult.result_datetime).label('date'), # Use result_datetime
            func.avg(LabResult.value_numeric).label('avg_value'), # Use value_numeric
            func.min(LabResult.value_numeric).label('min_value'), # Use value_numeric
            func.max(LabResult.value_numeric).label('max_value'), # Use value_numeric
            func.count(LabResult.id).label('tests_count')
        ).filter(
            cast(LabResult.result_datetime, SQLDate) >= start_date, # Cast to date for comparison
            cast(LabResult.result_datetime, SQLDate) <= end_date,
            LabResult.value_numeric.isnot(None) # Important for numeric aggregations
        )
        if test_name:
            query = query.filter(LabResult.test_name.ilike(f'%{test_name}%'))
        if patient_id_filter:
            query = query.filter(LabResult.patient_id == patient_id_filter)

        query = query.group_by(func.date(LabResult.result_datetime)).order_by(func.date(LabResult.result_datetime))
        results = query.all()

        trend_data = [{
            "date": row.date.isoformat(),
            "average_value": round(row.avg_value, 2) if row.avg_value is not None else None,
            "min_value": round(row.min_value, 2) if row.min_value is not None else None,
            "max_value": round(row.max_value, 2) if row.max_value is not None else None,
            "tests_count": row.tests_count
        } for row in results]

        return jsonify({
            "report_name": "Lab Result Trends", "test_name_filter": test_name or "All Numeric Tests",
            "patient_id_filter": patient_id_filter or "All Patients",
            "period_start": start_date_str, "period_end": end_date_str,
            "generated_at": datetime.utcnow().isoformat(), "trend_data": trend_data
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error generating lab result trends report: {e}")
        return jsonify({"error": "Could not generate lab result trends report."}), 500

@reports_bp.route('/reports/medication-usage', methods=['GET'])
@permission_required('report:read:medication_usage')
def medication_usage_report():
    # NOTE: This report assumes a 'MedicationAdministration' model or similar that logs
    # each time a medication is administered, with a numeric 'dosage_administered'
    # and 'administration_datetime'.
    # If you want to report on prescribed/active meds from 'PatientMedication',
    # the query and aggregation will be different (e.g., count of patients per med).
    current_app.logger.warning("Medication usage report endpoint is a placeholder and requires a specific 'MedicationAdministration' model or adjusted logic for 'PatientMedication'.")
    return jsonify({
        "report_name": "Medication Usage Report (Placeholder)",
        "message": "This report needs further implementation based on how medication administrations are logged.",
        "status": "Pending Implementation"
    }), 501 # Not Implemented

@reports_bp.route('/reports/task-completion', methods=['GET'])
@permission_required('report:read:task_completion')
def task_completion_report():
    try:
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        assigned_to_user_id_filter = request.args.get('assigned_to_user_id') # Corrected field name

        if not start_date_str or not end_date_str:
            return jsonify({"error": "start_date and end_date required (YYYY-MM-DD)"}), 400
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({"error": "Invalid date format for start_date/end_date. Use YYYY-MM-DD."}), 400

        query = db.session.query(
            Task.status, func.count(Task.id).label('count')
        ).filter(
            cast(Task.created_at, SQLDate) >= start_date, # Assuming tasks created in period
            cast(Task.created_at, SQLDate) <= end_date
        )
        if assigned_to_user_id_filter:
            query = query.filter(Task.assigned_to_user_id == assigned_to_user_id_filter) # Use correct field

        query = query.group_by(Task.status)
        results = query.all()

        status_counts = {row.status: row.count for row in results}
        total_tasks = sum(status_counts.values())
        completed_count = status_counts.get('Completed', 0) # Get count for 'Completed' status
        completion_rate = round((completed_count / total_tasks) * 100, 2) if total_tasks > 0 else 0

        return jsonify({
            "report_name": "Task Completion Report",
            "period_start": start_date_str, "period_end": end_date_str,
            "generated_at": datetime.utcnow().isoformat(),
            "total_tasks_in_period": total_tasks,
            "completion_rate_percent": completion_rate,
            "tasks_by_status": status_counts,
            "assigned_to_filter": assigned_to_user_id_filter or "All Users"
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error generating task completion report: {e}")
        return jsonify({"error": "Could not generate task completion report."}), 500

@reports_bp.route('/reports/average-length-of-stay', methods=['GET'])
@permission_required('report:read:length_of_stay')
def average_length_of_stay_report():
    # NOTE: This report requires 'admission_date' and 'discharge_date' (DateTime fields)
    # on the Patient model. These fields need to be added to models.py.
    if not (hasattr(Patient, 'admission_date') and hasattr(Patient, 'discharge_date')):
        current_app.logger.warning("ALOS report called, but Patient model missing admission_date/discharge_date fields.")
        return jsonify({"error": "Patient model is missing necessary date fields for ALOS calculation."}), 501

    try:
        start_date_str = request.args.get('start_date') # Filters by discharge_date
        end_date_str = request.args.get('end_date')   # Filters by discharge_date

        query = Patient.query.filter(
            Patient.admission_date.isnot(None),
            Patient.discharge_date.isnot(None),
            Patient.discharge_date >= Patient.admission_date # Ensure logical consistency
        )

        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                query = query.filter(cast(Patient.discharge_date, SQLDate) >= start_date)
            except ValueError: return jsonify({"error": "Invalid start_date format."}), 400
        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                query = query.filter(cast(Patient.discharge_date, SQLDate) <= end_date)
            except ValueError: return jsonify({"error": "Invalid end_date format."}), 400

        discharged_patients = query.all()
        if not discharged_patients:
            return jsonify({
                "report_name": "Average Length of Stay Report",
                "message": "No discharged patients found in the specified period with valid admission/discharge dates.",
                "total_patients_discharged": 0, "average_length_of_stay_days": 0
            }), 200

        lengths_of_stay_days = []
        for p in discharged_patients:
            los = (p.discharge_date.date() - p.admission_date.date()).days # Calculate LOS in days
            if los >= 0 : # Only consider valid LOS
                 lengths_of_stay_days.append(los)


        average_stay = round(sum(lengths_of_stay_days) / len(lengths_of_stay_days), 2) if lengths_of_stay_days else 0

        return jsonify({
            "report_name": "Average Length of Stay Report",
            "period_start_filter_on_discharge": start_date_str or "N/A",
            "period_end_filter_on_discharge": end_date_str or "N/A",
            "generated_at": datetime.utcnow().isoformat(),
            "total_patients_considered_for_alos": len(lengths_of_stay_days),
            "average_length_of_stay_days": average_stay
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error generating average length of stay report: {e}")
        return jsonify({"error": "Could not generate average length of stay report."}), 500
