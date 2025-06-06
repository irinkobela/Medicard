# hms_app_pkg/audit/listeners.py
from sqlalchemy import event
from sqlalchemy.orm import attributes
from flask import g
from ..models import Patient, Order
from .services import create_audit_log # Import our new service

@event.listens_for(Patient, 'after_insert')
def after_patient_insert(mapper, connection, target):
    """Listen for new Patient records."""
    details = {"message": f"New patient '{target.first_name} {target.last_name}' created with MRN {target.mrn}."}
    create_audit_log(
        action="PATIENT_CREATE",
        target_model="Patient",
        target_id=target.id,
        change_details=details
    )

@event.listens_for(Patient, 'after_update')
def after_patient_update(mapper, connection, target):
    """Listen for updates to Patient records."""
    changes = {}
    # Loop through all changed attributes and record their old and new values
    for attr in attributes.instance_state(target).history.sum():
        if attr.key not in ['updated_at']: # Don't log the 'updated_at' change itself
            changes[attr.key] = {"new": attr.value[0], "old": attr.value[2]}
    if changes:
        create_audit_log(
            action="PATIENT_UPDATE",
            target_model="Patient",
            target_id=target.id,
            change_details=changes
        )

@event.listens_for(Order, 'after_update')
def after_order_update(mapper, connection, target):
    """Listen for updates to Order records, like signing or discontinuing."""
    changes = {}
    for attr in attributes.instance_state(target).history.sum():
        # We only want to log important status changes for this example
        if attr.key == 'status':
            changes[attr.key] = {"new": attr.value[0], "old": attr.value[2]}
    if changes:
         create_audit_log(
             action="ORDER_STATUS_CHANGE",
             target_model="Order",
             target_id=target.id,
             change_details=changes
         )

def register_audit_listeners():
    """This function is called by the app factory to activate the listeners."""
    print("Audit listeners registered.")