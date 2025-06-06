# hms_app_pkg/cds/services.py
from ..models import Patient, Order, OrderableItem, PatientAllergy, PatientMedication, CDSRule
from flask import current_app

def execute_cds_checks(patient: Patient, order_item: OrderableItem, order_details: dict):
    """
    Main service function to run all relevant clinical decision support checks.
    It gathers alerts from different check functions.

    Args:
        patient: The patient object for whom the order is being placed.
        order_item: The OrderableItem object being ordered.
        order_details: The dictionary of details for the new order.

    Returns:
        A list of alert dictionaries.
    """
    alerts = []

    # Run each type of check and collect any alerts
    alerts.extend(_check_for_duplicate_orders(patient, order_item))
    alerts.extend(_check_for_allergies(patient, order_item))
    alerts.extend(_check_drug_drug_interactions(patient, order_item))
    alerts.extend(_check_dose_range(order_item, order_details))

    current_app.logger.info(f"CDS checks for patient {patient.id} on item {order_item.name} resulted in {len(alerts)} alert(s).")
    return alerts


def _check_for_duplicate_orders(patient: Patient, order_item: OrderableItem):
    """Checks if an active order for the same item already exists."""
    # This rule could be loaded from the CDSRule table for more flexibility
    existing_active_order = Order.query.filter_by(
        patient_id=patient.id,
        orderable_item_id=order_item.id,
        status='Active'
    ).first()

    if existing_active_order:
        return [{
            "type": "DUPLICATE_ORDER",
            "message": f"Warning: An active order for '{order_item.name}' already exists for this patient.",
            "severity": "Warning"
        }]
    return []


def _check_for_allergies(patient: Patient, order_item: OrderableItem):
    """Checks the ordered item against the patient's documented allergies."""
    if order_item.item_type != 'Medication':
        return []

    patient_allergies = PatientAllergy.query.filter_by(patient_id=patient.id, is_active=True).all()
    for allergy in patient_allergies:
        # Simple check: does the allergy name appear in the medication name?
        if allergy.allergen_name.lower() in order_item.name.lower():
            return [{
                "type": "ALLERGY_ALERT",
                "message": f"Critical: Patient has a documented allergy to '{allergy.allergen_name}'. This order for '{order_item.name}' may be unsafe.",
                "severity": "Critical"
            }]
    return []


def _check_drug_drug_interactions(patient: Patient, new_med_item: OrderableItem):
    """
    Checks for potential drug-drug interactions.
    NOTE: This is a simplified placeholder. A real implementation would use a
    dedicated drug interaction database or API (e.g., RxNorm, Med-RT).
    """
    if new_med_item.item_type != 'Medication':
        return []

    # This is where we would load interaction rules from our CDSRule table
    interaction_rule = CDSRule.query.filter_by(rule_type='DrugInteraction', is_active=True).first()
    if not interaction_rule:
        return [] # No interaction rules defined

    # Get the patient's current active inpatient medications
    active_meds = PatientMedication.query.join(OrderableItem).filter(
        PatientMedication.patient_id == patient.id,
        PatientMedication.status == 'Active',
        PatientMedication.type == 'INPATIENT_ACTIVE'
    ).all()
    
    active_med_names = {med.orderable_item.name.lower() for med in active_meds if med.orderable_item}

    # Example Rule Logic: The rule_logic JSON defines pairs of interacting drugs
    # e.g., {"interactions": [["warfarin", "aspirin"], ["lisinopril", "spironolactone"]]}
    defined_interactions = interaction_rule.rule_logic.get("interactions", [])
    new_med_name_lower = new_med_item.name.lower()

    for drug1, drug2 in defined_interactions:
        if (new_med_name_lower in drug1 and drug2 in active_med_names) or \
           (new_med_name_lower in drug2 and drug1 in active_med_names):
            return [{
                "type": "DRUG_INTERACTION",
                "message": f"Warning: Potential interaction between the new order '{new_med_item.name}' and an existing medication. Please review patient's medication list.",
                "severity": "Warning"
            }]

    return []


def _check_dose_range(order_item: OrderableItem, order_details: dict):
    """
    Checks if the ordered dose is within a safe, predefined range.
    Assumes order_details might contain keys like 'dose' and 'unit'.
    """
    if order_item.item_type != 'Medication' or not order_item.max_dose:
        # Not a medication or no dose range is defined for this item, so we can't check.
        return []

    try:
        # The frontend should send dose and unit in the order_details dictionary
        ordered_dose = float(order_details.get("dose"))
        ordered_unit = order_details.get("unit")
    except (ValueError, TypeError, AttributeError):
        # Cannot check dose if it's not provided or not a number.
        return []

    # Check if the units match before comparing the numbers
    if ordered_unit and order_item.default_dose_unit and ordered_unit.lower() != order_item.default_dose_unit.lower():
        return [{
            "type": "DOSE_UNIT_MISMATCH",
            "message": f"Warning: The ordered unit '{ordered_unit}' does not match the default unit '{order_item.default_dose_unit}' for {order_item.name}.",
            "severity": "Warning"
        }]

    # Finally, perform the dose range check
    min_dose = order_item.min_dose or 0  # Assume 0 if no minimum is set
    max_dose = order_item.max_dose

    if not (min_dose <= ordered_dose <= max_dose):
        return [{
            "type": "DOSE_RANGE_ALERT",
            "message": f"Warning: The ordered dose of {ordered_dose} {ordered_unit} is outside the recommended range of {min_dose}-{max_dose} {order_item.default_dose_unit} for {order_item.name}.",
            "severity": "Warning"
        }]
    return []