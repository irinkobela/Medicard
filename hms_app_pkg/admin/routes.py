# hms_app_pkg/admin/routes.py
from flask import Blueprint, jsonify, current_app
from .. import db
from ..models import Role, Permission, User, OrderableItem, CDSRule # Ensure all needed models are here
# from ..models import Patient, Task, etc. # If creating sample data for these
from ..utils import permission_required # If you protect this endpoint

admin_bp = Blueprint('admin_bp', __name__)

@admin_bp.route('/setup-roles-permissions', methods=['POST'])
# @permission_required('admin:manage_system_setup') # Recommended to protect this
def setup_roles_permissions():
    try:
        # Comprehensive Permissions Data (name: description)
        permissions_data = {
            'patient:read': 'Can read patient data',
            'patient:create': 'Can create new patients',
            'patient:read:own': 'Can read own assigned patients or patients on their service',
            'patient:update': 'Can update patient data they are responsible for',
            "patient:read:summary": 'Can read patient summary data',

            'note:create': 'Can create clinical notes',
            'note:read': 'Can read clinical notes (pertaining to accessible patients)',
            'note:sign': 'Can sign clinical notes they authored or are responsible for',

            'order:create': 'Can create new orders',
            'order:read': 'Can read orders (for accessible patients)',
            'order:sign': 'Can sign orders they are responsible for (general)',
            'order:sign:medication': 'Can sign medication orders (specific, if different rules apply)',
            'order:discontinue': 'Can discontinue orders',
            'order:read_catalog': 'Can browse orderable items from the catalog',

            'task:create': 'Can create new tasks',
            'task:read:own': 'Can read tasks assigned to or created by self',
            'task:read:any': 'Can read any task (supervisor/admin)',
            'task:update:own': 'Can update tasks assigned to or created by self',
            'task:update:any': 'Can update any task (supervisor/admin)',
            'task:delete:own': 'Can delete/cancel tasks created by self (if workflow allows)',
            'task:delete:any': 'Can delete/cancel any task (admin)',

            'vitals:record': 'Can record patient vital signs',
            'vitals:read': 'Can read patient vital signs',
            'vitals:update': 'Can update/correct vital signs entries they recorded (or with :any)',
            'vitals:update:any': 'Can update/correct any vital signs entry',
            'vitals:delete': 'Can delete vital signs entries (restricted)',
            'vitals:delete:any': 'Can delete any vital signs entry (highly restricted admin)',
            'vitals:read:derived_scores': 'Can view derived clinical scores from vitals',

            'rounding_note:create': 'Can create clinical rounding notes',
            'rounding_note:read': 'Can read clinical rounding notes',
            'rounding_note:update': 'Can update their own rounding notes (if not finalized)',
            'rounding_note:update:any': 'Can update any rounding note (supervisor/admin)',
            'rounding_note:update:finalized': 'Can amend/addend finalized rounding notes (supervisor/admin)',
            'rounding_note:finalize': 'Can finalize their own clinical rounding notes',
            'rounding_note:finalize:any': 'Can finalize any clinical rounding note (supervisor/admin)',
            'rounding_note:review': 'Can review and co-sign/attest to rounding notes',
            'rounding_note:read:any': 'Can read all rounding notes (supervisor/admin)',

            'handoff:create': 'Can create handoff entries',
            'handoff:read': 'Can read handoff entries (relevant to their role/patients)',
            'handoff:read:any': 'Can read any handoff entry',
            'handoff:update': 'Can update their own handoff entries (if not reviewed/finalized)',
            'handoff:update:any': 'Can update any handoff entry',
            'handoff:update:reviewed': 'Can update/append to reviewed handoff entries (with audit)',
            'handoff:review': 'Can mark handoff entries as reviewed',
            'handoff:delete': 'Can delete their own handoff entries (if allowed)',
            'handoff:delete:any': 'Can delete any handoff entry (admin)',

            'flag:create': 'Can create patient flags/alerts',
            'flag:read': 'Can read patient flags',
            'flag:read:any': 'Can read all patient flags',
            'flag:update': 'Can update flags they created',
            'flag:update:any': 'Can update any patient flag',
            'flag:review': 'Can review/acknowledge patient flags',
            'flag:deactivate': 'Can deactivate flags they created or are responsible for',
            'flag:deactivate:any': 'Can deactivate any patient flag',

            'discharge_plan:create': 'Can create/initiate discharge plans',
            'discharge_plan:read': 'Can read discharge plans (for accessible patients)',
            'discharge_plan:read:any': 'Can read all discharge plans (coordinator/admin)',
            'discharge_plan:update': 'Can update discharge plans they are involved with',
            'discharge_plan:update:any': 'Can update any discharge plan (coordinator/admin)',
            'discharge_plan:delete': 'Can delete discharge plans (restricted)',
            'discharge_plan:delete:any': 'Can delete any discharge plan (admin)',
            'discharge_plan:review': 'Can review/approve discharge plans',
            'discharge_plan:manage_home_meds': 'Can manage home medications within discharge plans',
            'discharge_plan:reconcile': 'Can perform medication reconciliation within discharge plans',

            'medication:read': 'Can read patient medication lists (MAR, Home, Discharge)',
            'medication:manage_home_meds': 'Can add/update patient home medications list',
            'medication:update': 'Can update existing medication records (e.g., status, inpatient MAR changes)',
            'medication:reconcile': 'Can perform and log medication reconciliation',
            'medication:reconcile:read_log': 'Can read medication reconciliation logs',
            'medication:administer': 'Can document medication administration (MAR)',
            'medication:administer:any': 'Can document medication administration for any patient (nurse/pharmacist)',
            'mar:read': 'Can read the Medication Administration Record',
            'mar:document_administration': 'Can create a new MAR entry (i.e., document giving a med)',

            'notification:read': 'Can read own notifications',
            'notification:update': 'Can update own notifications (e.g., mark as read)',
            'notification:delete': 'Can delete own notifications',
            'notification:create_system': '(System Use) Allows system components to create notifications',
            'notification:any': 'Can read all notifications (admin)',

            'result:read:lab': 'Can read lab results',
            'result:read:imaging': 'Can read imaging results',
            'result:read:consult': 'Can read consult results/notes',
            'result:read:any': 'Can read all types of results (supervisor/admin)',
            'result:acknowledge:lab': 'Can acknowledge lab results',
            'result:acknowledge:imaging': 'Can acknowledge imaging results',
            'result:acknowledge:consult': 'Can acknowledge consult results',
            'result:acknowledge:all': 'Can acknowledge all types of results (supervisor/admin)',
            'result:review:lab': 'Can review and interpret lab results (e.g., add interpretation)',
            'result:review:imaging': 'Can review and interpret imaging results',
            'result:review:consult': 'Can review and interpret consult notes',
            'result:review:any': 'Can review/interpret all results (specialist/admin)',
            'result:create:lab': 'Can create new lab results (e.g., from external systems)',
            'result:create:imaging': 'Can create new imaging results (e.g., from external systems)',
            'result:create:consult': 'Can create new consult results (e.g., from external systems)',
            'result:create:any': '(Admin) Can create any type of result (e.g., from external systems)',
            # Delete permissions for results are highly sensitive
            'result:delete:lab': '(Admin) Can delete lab results',
            'result:delete:imaging': '(Admin) Can delete imaging results',
            'result:delete:consult': '(Admin) Can delete consult results',
            'result:delete:any': '(Admin) Can delete any type of result',

            'orderable_item:read_catalog': 'Can read the catalog of orderable items',
            'orderable_item:read': 'Can read detailed information of orderable items',
            'orderable_item:create': '(Admin) Can create new orderable items',
            'orderable_item:update': '(Admin) Can update existing orderable items',
            'orderable_item:delete': '(Admin) Can delete orderable items',
            'orderable_item:manage_catalog': '(Admin) Can manage the entire catalog of orderable items',

            'appointment:create': 'Can create new appointments',
            'appointment:read': 'Can read appointment details (own or permitted)',
            'appointment:read:own': 'Can read their own appointments (as provider or patient)',
            'appointment:read:any': 'Can read any appointment (scheduler/admin)',
            'appointment:update': 'Can update existing appointments (own or permitted)',
            'appointment:update:any': 'Can update any appointment (scheduler/admin)',
            'appointment:cancel': 'Can cancel appointments (own or permitted)',
            'appointment:cancel:any': 'Can cancel any appointment (scheduler/admin)',
            'appointment:reschedule': 'Can reschedule appointments (own or permitted)',
            'appointment:reschedule:any': 'Can reschedule any appointment (scheduler/admin)',
            'appointment:manage_schedule': '(Scheduler/Admin) Can manage appointment schedules',
            # 'appointment:delete' and 'appointment:delete:any' were present but often 'cancel' is preferred.
            # If hard delete is needed, it should be highly restricted.

            'report:read:patient_demographics': 'Can read patient demographics reports',
            'report:read:appointment_stats': 'Can read appointment statistics reports',
            'report:read:lab_result_trend': 'Can read lab result trends report',
            'report:read:medication_usage': 'Can read medication usage report',
            'report:read:task_completion': 'Can read task completion report',
            'report:read:length_of_stay': 'Can read length of stay report',
            'report:read:all': 'Can read all available reports',
            'user:profile:read': 'Can read own user profile', # From auth blueprint
            'user:logout': 'Can log out', # From auth blueprint
            'dashboard:read': 'Can view their personal dashboard summary',
            'cds:execute': 'Can execute Clinical Decision Support checks',
            'patient:read:timeline': 'Can read the patient event timeline',



            'admin:manage_users': '(Admin) Can manage user accounts',
            'admin:manage_roles': '(Admin) Can manage user roles',
            'admin:manage_permissions': '(Admin) Can manage system permissions',
            'admin:manage_system_setup': '(Admin) Can perform system setup tasks'
        }
        created_permissions = {}
        for name, desc in permissions_data.items():
            perm = Permission.query.filter_by(name=name).first()
            if not perm:
                perm = Permission(name=name, description=desc)
                db.session.add(perm)
            created_permissions[name] = perm
        db.session.commit()

        # --- Define Roles and Assign Permissions ---
        roles_config = {
            'AttendingPhysician': [
                # Patient & Notes
                'patient:read', 'patient:create', 'patient:read:own',
                'note:create', 'note:read', 'note:sign', 'patient:read:summary'
                # Orders
                'order:create', 'order:read', 'order:sign', 'order:discontinue', 'order:read_catalog', 'order:sign:medication',
                # Tasks
                'task:create', 'task:read:own', 'task:read:any', # Can see tasks for their team/all patients
                'task:update:own', 'task:update:any', # Can update tasks for team
                # Vitals
                'vitals:record', 'vitals:read', 'vitals:update', 'vitals:read:derived_scores',
                # Rounds, Handoffs, Flags (Full control for their patients)
                'rounding_note:create', 'rounding_note:read', 'rounding_note:update', 'rounding_note:finalize', 'rounding_note:review', 'rounding_note:read:any',
                'handoff:create', 'handoff:read', 'handoff:read:any', 'handoff:update', 'handoff:review',
                'flag:create', 'flag:read', 'flag:update', 'flag:review', 'flag:deactivate',
                # Discharge & Meds
                'discharge_plan:create', 'discharge_plan:read', 'discharge_plan:update', 'discharge_plan:review', 'discharge_plan:reconcile', 'discharge_plan:manage_home_meds',
                'medication:read', 'medication:manage_home_meds', 'medication:update', 'medication:reconcile', 'medication:reconcile:read_log',
                # Notifications
                'notification:read', 'notification:update', 'notification:delete',
                # Results (Full capabilities)
                'result:read:lab', 'result:read:imaging', 'result:read:consult', 'result:read:any',
                'result:acknowledge:lab', 'result:acknowledge:imaging', 'result:acknowledge:consult', 'result:acknowledge:all',
                'result:review:lab', 'result:review:imaging', 'result:review:consult', 'result:review:any',
                'result:create:lab', 'result:create:imaging', 'result:create:consult', # Can create/order these
                # Appointments (for self)
                'appointment:read:own', 'appointment:create', 'appointment:update', 'appointment:cancel', 'appointment:reschedule',
                # Reports
                'report:read:all', # Attendings often need full reporting access
                # User Profile
                'user:profile:read', 'user:logout',
                'dashboard:read',
                'cds:execute',
                'mar:read', 'mar:document_administration', 'patient:read:timeline',
            ],
            'Resident': [
                'patient:read', 'patient:read:own', 'patient:read:summary'
                'note:create', 'note:read', # Cannot sign, needs co-signature
                'order:create', 'order:read', 'order:read_catalog', # Cannot sign, needs co-signature
                'task:create', 'task:read:own', 'task:update:own',
                'vitals:record', 'vitals:read', 'vitals:update', 'vitals:read:derived_scores',
                'rounding_note:create', 'rounding_note:read', 'rounding_note:update', # Cannot finalize/review without attending
                'handoff:create', 'handoff:read', 'handoff:update',
                'flag:create', 'flag:read', 'flag:update', 'flag:deactivate',
                'discharge_plan:create', 'discharge_plan:read', 'discharge_plan:update', # Contributes to plan
                'medication:read', 'medication:manage_home_meds', 'medication:reconcile:read_log',
                'notification:read', 'notification:update', 'notification:delete',
                'result:read:lab', 'result:read:imaging', 'result:read:consult',
                'result:acknowledge:lab', 'result:acknowledge:imaging', 'result:acknowledge:consult', # Can acknowledge routine results
                'appointment:read:own', 'mar:read', # <-- ADD
            'mar:document_administration', 'patient:read:timeline',
                'user:profile:read', 'user:logout', 'dashboard:read', 'cds:execute',
            ],
            'Nurse': [
                'patient:read', 'patient:read:own', 'patient:read:summary'
                'note:create', 'note:read', # Nursing notes
                'order:read', # View orders to carry them out
                'task:create', 'task:read:own', 'task:update:own', # Manage their tasks
                'vitals:record', 'vitals:read', 'vitals:update', 'vitals:read:derived_scores',
                'rounding_note:read', 'handoff:read', 'handoff:create', # Participate in handoffs
                'flag:create', 'flag:read', 'flag:deactivate', # Can create and deactivate flags (e.g., fall risk)
                'discharge_plan:read', 'discharge_plan:update', # Contribute to discharge planning
                'medication:read', 'medication:administer', # Critical permission
                'notification:read', 'notification:update', 'notification:delete',
                'result:read:lab', 'result:acknowledge:lab', # Acknowledge routine labs
                'appointment:read', # View patient appointments 
            'mar:document_administration', 'mar:read', 'patient:read:timeline',
                'user:profile:read', 'user:logout', 'dashboard:read', 'cds:execute'
            ],
            'Pharmacist': [ 
                'patient:read', 
                'order:read', 'order:read_catalog', 'order:sign:medication', # Verify/approve med orders
                'medication:read', 'medication:manage_home_meds', 'medication:reconcile', 'medication:reconcile:read_log', 'medication:update',
                'discharge_plan:read', 'discharge_plan:reconcile', 'discharge_plan:manage_home_meds',
                'notification:read', 'notification:update', 'notification:delete',
                'result:read:lab', # For drug-lab interactions, monitoring
                'user:profile:read', 'user:logout', 'dashboard:read', 'cds:execute', 'mar:read',
            ],
            'CaseManager': [ 
                'patient:read', 'patient:read:own','patient:read:summary',
                'task:create', 'task:read:own', 'task:update:own',
                'discharge_plan:create', 'discharge_plan:read', 'discharge_plan:update', 'discharge_plan:delete',
                'discharge_plan:review', 'discharge_plan:read:any',
                'notification:read', 'notification:update', 'notification:delete',
                'handoff:read', 'flag:read', 
                'appointment:read', 'report:read:length_of_stay', # Relevant report for this role
                'user:profile:read', 'user:logout', 'dashboard:read', 'cds:execute',
            ],
            'Scheduler': [ # Example role for schedulers
                'patient:read', 'patient:create', # To find and register patients for scheduling
                'appointment:create', 'appointment:read:any', 'appointment:update:any', 
                'appointment:cancel:any', 'appointment:reschedule:any', 'appointment:manage_schedule',
                'notification:read', 'notification:update', 'notification:delete',
                'user:profile:read', 'user:logout', 'dashboard:read', 'cds:execute',
            ],
            'SystemAdmin': list(permissions_data.keys()) # Gets all permissions
        }

        for role_name, perm_names_for_role in roles_config.items():
            role = Role.query.filter_by(name=role_name).first()
            if not role:
                role = Role(name=role_name, description=f'{role_name} role.')
                db.session.add(role)
                db.session.flush() 

            current_role_perms_names = {p.name for p in role.permissions}
            
            for perm_name in perm_names_for_role:
                if perm_name in created_permissions and perm_name not in current_role_perms_names:
                     role.permissions.append(created_permissions[perm_name])
            
            # Optional: Logic to remove permissions from a role if they are no longer in perm_names_for_role
            # permissions_to_remove = [p for p in role.permissions if p.name not in perm_names_for_role]
            # for p_to_remove in permissions_to_remove:
            #    role.permissions.remove(p_to_remove)
                
        db.session.commit()

        # Sample OrderableItems (as before)
        if not OrderableItem.query.first():
            sample_items_data = [
                {'item_type': 'Medication', 'name': 'Aspirin 81mg Tablet', 'generic_name': 'Aspirin', 'code': 'NDC-ASP81', 'min_dose': 81, 'max_dose': 650, 'default_dose_unit': 'mg'},
                {'item_type': 'Medication', 'name': 'Lisinopril 10mg Tablet', 'generic_name': 'Lisinopril', 'code': 'NDC-LIS10', 'min_dose': 2.5, 'max_dose': 40, 'default_dose_unit': 'mg'},
                {'item_type': 'LabTest', 'name': 'Complete Blood Count (CBC)', 'code': 'LOINC-CBC'},
                {'item_type': 'ImagingStudy', 'name': 'Chest X-Ray, 2 Views', 'code': 'CPT-CHESTXRAY'},
                {'item_type': 'Consult', 'name': 'Cardiology Consult', 'code': 'CONS-CARDIO'},
            ]
            for item_dict in sample_items_data:
                item = OrderableItem(**item_dict)
                db.session.add(item)
            db.session.commit()
            current_app.logger.info("Added sample orderable items.")

        # Sample CDS Rule for Drug-Drug Interaction
        if not CDSRule.query.filter_by(rule_type='DrugInteraction').first():
            interaction_rule = CDSRule(
                rule_name="Warfarin and Aspirin Interaction Alert",
                description="Alerts when Aspirin is ordered for a patient already on Warfarin, or vice-versa.",
                rule_type="DrugInteraction",
                rule_logic={
                    "interactions": [
                        # Each sub-list is a pair of interacting drug names (should be lowercase)
                        ["warfarin", "aspirin"]
                    ]
                },
                is_active=True
            )
            db.session.add(interaction_rule)
            current_app.logger.info("Added sample Drug-Drug Interaction CDS rule.")

        db.session.commit()
        return jsonify({"message": "Roles and permissions setup/updated successfully."}), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error setting up roles/permissions: {str(e)}", exc_info=True) # Add exc_info for full traceback
        return jsonify({"message": "Error setting up roles/permissions", "error": str(e)}), 500

# ... (other admin routes if any)
