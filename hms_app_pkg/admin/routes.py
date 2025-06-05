# hms_app_pkg/admin/routes.py
from flask import Blueprint, jsonify, current_app
from .. import db
from ..models import Role, Permission, User, OrderableItem # <<< CORRECTED IMPORT HERE
# ... other necessary model imports if you're creating sample data for them ...
from ..utils import permission_required

admin_bp = Blueprint('admin_bp', __name__)

@admin_bp.route('/setup-roles-permissions', methods=['POST'])
# @permission_required('admin:manage_system_setup') # Ideally, protect this
def setup_roles_permissions():
    try:
        # Permissions Data (name: description)
        permissions_data = {
            'patient:read': 'Can read patient data',
            'patient:create': 'Can create new patients',
            'patient:read:own': 'Can read own assigned patients',
            'note:create': 'Can create clinical notes',
            'note:read': 'Can read clinical notes',
            'note:sign': 'Can sign clinical notes',
            'order:create': 'Can create new orders',
            'order:read': 'Can read orders',
            'order:sign:medication': 'Can sign medication orders',
            'order:read_catalog': 'Can browse orderable items',
            'order:sign': 'Can sign any order type (general)',
            'order:discontinue': 'Can discontinue orders',

            'task:create': 'Can create new tasks',
            'task:read:own': 'Can read tasks assigned to or created by self',
            'task:read:any': 'Can read any task (admin/supervisor)',
            'task:update:own': 'Can update tasks assigned to or created by self',
            'task:update:any': 'Can update any task (admin/supervisor)',
            'task:delete:own': 'Can delete tasks created by self (if allowed)',
            'task:delete:any': 'Can delete any task (admin)',

            'vitals:record': 'Can record patient vital signs',
            'vitals:read': 'Can read patient vital signs',
            'vitals:update': 'Can update/correct vital signs entries',
            'vitals:delete': 'Can delete vital signs entries',
            'vitals:read:derived_scores': 'Can view derived clinical scores from vitals',

            'rounding_note:create': 'Can create clinical rounding notes',
            'rounding_note:read': 'Can read clinical rounding notes',
            'rounding_note:update': 'Can update their own clinical rounding notes (if not finalized)',
            'rounding_note:update:any': 'Can update any clinical rounding note (admin)',
            'rounding_note:update:finalized': 'Can update finalized rounding notes (supervisor/admin)',
            'rounding_note:finalize': 'Can finalize their own clinical rounding notes',
            'rounding_note:finalize:any': 'Can finalize any clinical rounding note (admin)',
            'rounding_note:review': 'Can review clinical rounding notes',
            'rounding_note:read:any': 'Can read all rounding notes (admin/supervisor)',

            'handoff:create': 'Can create handoff entries',
            'handoff:read': 'Can read handoff entries',
            'handoff:update': 'Can update their own handoff entries (if not reviewed)',
            'handoff:update:any': 'Can update any handoff entry (admin)',
            'handoff:update:reviewed': 'Can update reviewed handoff entries (supervisor/admin)',
            'handoff:review': 'Can review handoff entries',
            'handoff:delete': 'Can delete their own handoff entries (if allowed)',
            'handoff:delete:any': 'Can delete any handoff entry (admin)',

            'flag:create': 'Can create patient flags',
            'flag:read': 'Can read patient flags',
            'flag:update': 'Can update their own patient flags',
            'flag:update:any': 'Can update any patient flag (admin)',
            'flag:review': 'Can review patient flags',
            'flag:deactivate': 'Can deactivate their own patient flags',
            'flag:deactivate:any': 'Can deactivate any patient flag (admin)',
            
            'discharge_plan:create': 'Can create discharge plans',
            'discharge_plan:read': 'Can read discharge plans',
            'discharge_plan:update': 'Can update discharge plans', 
            'discharge_plan:delete': 'Can delete discharge plans', 
            'discharge_plan:review': 'Can review discharge plans',
            'discharge_plan:read:any': 'Can read all discharge plans (admin/coordinator)',
            'discharge_plan:manage_home_meds': 'Can manage home medications in discharge plans',
            'discharge_plan:reconcile': 'Can perform medication reconciliation in discharge plans',
            'discharge_plan:update:any': 'Can update any discharge plan (admin/coordinator)', 
            'discharge_plan:delete:any': 'Can delete any discharge plan (admin)',
            
            'medication:read': 'Can read patient medication lists (MAR, Home, Discharge)',
    'medication:manage_home_meds': 'Can add, update, and manage patient home medications list',
    'medication:update': 'Can update existing medication records (e.g., status, end_date)',
    'medication:reconcile': 'Can perform and log medication reconciliation',
    'medication:reconcile:read_log': 'Can read medication reconciliation logs',
    'medication:administer': 'Can document medication administration',
    'notification:read': 'Can read own notifications',
    'notification:update': 'Can update own notifications (e.g., mark as read)',
    'notification:delete': 'Can delete own notifications',
    'notification:create_system': 'Allows system components to create notifications (not for direct user assignment)'
            , 
            'result:acknowledge:lab': 'Can acknowledge lab results',
            'result:acknowledge:imaging': 'Can acknowledge imaging results',
            'result:acknowledge:consult': 'Can acknowledge consult results',
            'result:acknowledge:all': 'Can acknowledge all types of results (admin)',
            'result:read:lab': 'Can read lab results',
            'result:read:imaging': 'Can read imaging results',
            'result:read:consult': 'Can read consult results',
            'result:read:any': 'Can read all types of results (admin)',
            'result:review:lab': 'Can review lab results',
            'result:review:imaging': 'Can review imaging results',
            'result:review:consult': 'Can review consult results',
            'result:review:any': 'Can review all types of results (admin)',
            'result:delete:lab': 'Can delete lab results',
            'result:delete:imaging': 'Can delete imaging results',
            'result:delete:consult': 'Can delete consult results',
            'result:delete:any': 'Can delete any type of result (admin)',
            'orderable_item:read': 'Can read orderable items (medications, labs, etc.)',
            'orderable_item:create': 'Can create new orderable items (admin)',
            'orderable_item:update': 'Can update existing orderable items (admin)',
            'orderable_item:delete': 'Can delete orderable items (admin)',
            'orderable_item:read_catalog': 'Can read the catalog of orderable items',
            'orderable_item:manage_catalog': 'Can manage the catalog of orderable items (admin)',

            'admin:manage_roles': 'Can manage user roles and permissions',
            'admin:manage_permissions': 'Can manage permissions and access control',
            'admin:manage_users': 'Can manage users and roles',
            'admin:manage_system_setup': 'Can perform system setup tasks'
        }
        created_permissions = {}
        for name, desc in permissions_data.items():
            perm = Permission.query.filter_by(name=name).first()
            if not perm:
                perm = Permission(name=name, description=desc)
                db.session.add(perm)
            created_permissions[name] = perm
        db.session.commit()

        roles_config = {
            'AttendingPhysician': [
                'patient:read', 'patient:create', 'note:create', 'note:read', 'note:sign',
                'order:create', 'order:read', 'order:sign:medication', 'order:read_catalog', 'order:sign', 'order:discontinue',
                'task:create', 'task:read:own', 'task:update:own', 'task:delete:own',
                'vitals:record', 'vitals:read', 'vitals:update', 'vitals:read:derived_scores',
                'rounding_note:create', 'rounding_note:read', 'rounding_note:update', 'rounding_note:finalize', 'rounding_note:review',
                'handoff:create', 'handoff:read', 'handoff:update', 'handoff:review', 'handoff:delete',
                'flag:create', 'flag:read', 'flag:update', 'flag:review', 'flag:deactivate',
                'discharge_plan:create', 'discharge_plan:read', 'discharge_plan:update', 'discharge_plan:delete',
                'discharge_plan:review', 'discharge_plan:reconcile', 'discharge_plan:manage_home_meds'
                'medication:read', 'medication:manage_home_meds', 'medication:update',
        'medication:reconcile', 'medication:reconcile:read_log', 'medication:administer', 
         'notification:read', 'notification:update', 'notification:delete', 
            ],
            'Resident': [
                'patient:read', 'patient:read:own', 'note:create', 'note:read', 'note:sign',
                'order:create', 'order:read', 'order:read_catalog',
                'result:acknowledge:lab', 'task:create', 'task:read:own', 'task:update:own',
                'vitals:record', 'vitals:read', 'vitals:update', 'vitals:read:derived_scores',
                'rounding_note:create', 'rounding_note:read', 'rounding_note:update',
        'rounding_note:finalize', 'rounding_note:review', 'handoff:create', 'handoff:read', 'handoff:update',
        'handoff:review', 'handoff:delete', 'flag:create', 'flag:read', 'flag:update', 'flag:review', 'flag:deactivate', 'flag:delete', 'flag:read:any',
        'discharge_plan:create', 'discharge_plan:read', 'discharge_plan:update', 
        'discharge_plan:delete', 'discharge_plan:review', 'discharge_plan:reconcile', 'discharge_plan:manage_home_meds'
         'medication:read', 'medication:manage_home_meds', 'medication:update',
        'medication:reconcile', 'medication:reconcile:read_log', 'medication:administer',  'notification:read', 'notification:update', 'notification:delete',
        'appointment:read', 'appointment:create', 'appointment:update', 'appointment:cancel','appointment:cancel:any',  'appointment:manage_schedule', 'appointment:read:own', 'appointment:read:any',

            ],

            'Nurse': [ 
                'patient:read', 'note:create', 'note:read', 'order:read_catalog', 'order:read',
                'task:create', 'task:read:own', 'task:update:own',
                'vitals:record', 'vitals:read', 'vitals:update', 'vitals:read:derived_scores',
                'rounding_note:read', 'rounding_note:create', 
                'handoff:read', 'handoff:create', 
                'flag:create', 'flag:read', 'flag:update',
                'discharge_plan:create', 'discharge_plan:read', 'discharge_plan:update',
                'discharge_plan:manage_home_meds' ,  'medication:read', 'medication:manage_home_meds', # Nurses heavily involved in home med collection
        'medication:update', 
        'medication:reconcile:read_log' 
        'medication:administer'
        'notification:read', 'notification:update', 'notification:delete',
            ],
            'Pharmacist': [ 
                'patient:read', 'order:read', 'order:read_catalog',
                'medication:read', 'medication:manage_home_meds', 'medication:reconcile', # Permissions from medications blueprint
                'discharge_plan:read', 'discharge_plan:reconcile', 'discharge_plan:manage_home_meds'
                'medication:read', 'medication:manage_home_meds', 'medication:update',
        'medication:reconcile', 'medication:reconcile:read_log', 'notification:read', 'notification:update', 'notification:delete',

            ],
            'CaseManager': [ 
                'patient:read', 'task:create', 'task:read:own', 'task:update:own',
                'discharge_plan:create', 'discharge_plan:read', 'discharge_plan:update', 'discharge_plan:delete',
                'discharge_plan:review', 'discharge_plan:read:any', 'notification:read', 'notification:update', 'notification:delete'
                ,
            ],
            'SystemAdmin': list(permissions_data.keys())
        }

        for role_name, perm_names_for_role in roles_config.items():
            role = Role.query.filter_by(name=role_name).first()
            if not role:
                role = Role(name=role_name, description=f'{role_name} role.')
                db.session.add(role)
                db.session.flush() 

            current_role_perms_names = {p.name for p in role.permissions}
            
            for perm_name in perm_names_for_role:
                if perm_name not in current_role_perms_names and created_permissions.get(perm_name):
                     role.permissions.append(created_permissions[perm_name])
                
        db.session.commit()

        # --- Optional: Create some sample OrderableItems if table is empty ---
        if not OrderableItem.query.first(): # Check if OrderableItem table is empty
            sample_items_data = [
                {'item_type': 'Medication', 'name': 'Aspirin 81mg Tablet', 'generic_name': 'Aspirin', 'code': 'NDC-ASP81'},
                {'item_type': 'Medication', 'name': 'Lisinopril 10mg Tablet', 'generic_name': 'Lisinopril', 'code': 'NDC-LIS10'},
                {'item_type': 'Medication', 'name': 'Metformin 500mg Tablet', 'generic_name': 'Metformin', 'code': 'NDC-MET500'},
                {'item_type': 'LabTest', 'name': 'Complete Blood Count (CBC)', 'code': 'LOINC-CBC'},
                {'item_type': 'LabTest', 'name': 'Basic Metabolic Panel (BMP)', 'code': 'LOINC-BMP'},
                {'item_type': 'LabTest', 'name': 'Troponin I', 'code': 'LOINC-TROP'},
                {'item_type': 'ImagingStudy', 'name': 'Chest X-Ray, 2 Views', 'code': 'CPT-CHESTXRAY'},
                {'item_type': 'ImagingStudy', 'name': 'CT Head without contrast', 'code': 'CPT-CTHEAD'},
                {'item_type': 'Consult', 'name': 'Cardiology Consult', 'code': 'CONS-CARDIO'},
                {'item_type': 'Consult', 'name': 'Nephrology Consult', 'code': 'CONS-NEPHRO'},
            ]
            for item_dict in sample_items_data: # Renamed variable to avoid conflict
                item = OrderableItem(**item_dict) # Use the loop variable item_dict
                db.session.add(item)
            db.session.commit()
            current_app.logger.info("Added sample orderable items.")

        return jsonify({"message": "Basic roles and permissions set up/updated successfully."}), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error setting up roles/permissions: {str(e)}")
        return jsonify({"message": "Error setting up roles/permissions", "error": str(e)}), 500

# ... (other admin routes if any)
