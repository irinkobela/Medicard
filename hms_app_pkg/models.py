from . import db # Imports the db instance from __init__.py
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import uuid
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
# --- Association Tables (Many-to-Many) ---
user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True)
)

role_permissions = db.Table('role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id'), primary_key=True)
)

# --- Model Definitions ---

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    hashed_password = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(120), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    is_ldap_user = db.Column(db.Boolean, default=False)
    mfa_secret = db.Column(db.String(120), nullable=True) # Encrypted
    mfa_enabled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # --- NEW FIELDS FOR PASSWORD RESET ---
    password_reset_token = db.Column(db.String(100), nullable=True, unique=True, index=True)
    password_reset_expires = db.Column(db.DateTime, nullable=True)
    # --- END NEW FIELDS ---

    roles = db.relationship('Role', secondary=user_roles, lazy='subquery',
                            backref=db.backref('users', lazy=True))

    def set_password(self, password):
        self.hashed_password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.hashed_password, password)

    def get_permissions(self):
        perms = set()
        for role in self.roles:
            for perm in role.permissions:
                perms.add(perm.name)
        return list(perms)

    def to_dict(self, include_permissions=True, include_roles=True):
        data = {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "is_active": self.is_active,
            "mfa_enabled": self.mfa_enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
        if include_roles:
            data["roles"] = [role.name for role in self.roles]
        if include_permissions: # May not always want to send this, e.g. in public user lists
            data["permissions"] = self.get_permissions()
        return data

    def __repr__(self):
        return f'<User {self.username}>'

class TokenBlacklist(db.Model):
    """
    Model for storing blacklisted JWT tokens (e.g., after logout).
    """
    __tablename__ = 'token_blacklist'
    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(36), nullable=False, unique=True, index=True) # JWT ID
    expires_at = db.Column(db.DateTime, nullable=False) # Should match token's expiry

    def __repr__(self):
        return f'<TokenBlacklist jti:{self.jti}>'

class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))
    permissions = db.relationship('Permission', secondary=role_permissions, lazy='subquery',
                                  backref=db.backref('roles', lazy=True))
    def __repr__(self):
        return f'<Role {self.name}>'

class Permission(db.Model):
    __tablename__ = 'permissions'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))
    def __repr__(self):
        return f'<Permission {self.name}>'

class Patient(db.Model):
    __tablename__ = 'patients'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mrn = db.Column(db.String(50), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(20))
    attending_physician_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    code_status = db.Column(db.String(50), default="Full Code")
    isolation_precautions = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    admission_date = db.Column(db.DateTime, nullable=True)
    discharge_date = db.Column(db.DateTime, nullable=True)


    known_cad = db.Column(db.Boolean, default=False, nullable=True) # Coronary Artery Disease
    congestive_heart_failure = db.Column(db.Boolean, default=False, nullable=True)
    hypertension = db.Column(db.Boolean, default=False, nullable=True)
    diabetes = db.Column(db.Boolean, default=False, nullable=True)
    stroke_or_tia = db.Column(db.Boolean, default=False, nullable=True) # Stroke or Transient Ischemic Attack
    vascular_disease = db.Column(db.Boolean, default=False, nullable=True) # e.g., PAD, MI, Aortic Plaque
    # Atrial Fibrillation (afib) might be a problem list item or a specific flag.
    # For simplicity, adding a direct flag here.
    atrial_fibrillation = db.Column(db.Boolean, default=False, nullable=True)
    notes = db.relationship('ClinicalNote', backref='patient', lazy='dynamic')
    problems = db.relationship('PatientProblemList', backref='patient', lazy='dynamic')
    orders = db.relationship('Order', backref='patient', lazy='dynamic')
    allergies = db.relationship('PatientAllergy', backref='patient', lazy='dynamic')
    # Add backrefs for new models if they were in your previous version of models.py
    tasks = db.relationship(
        'Task',
        foreign_keys='Task.patient_id', # Explicitly state the foreign key
        backref='patient',              # This will create `task.patient`
        lazy='dynamic',
        order_by="desc(Task.created_at)"
    )

    @property
    def age(self):
        if self.date_of_birth:
            today = datetime.date.today()
            return today.year - self.date_of_birth.year - \
                   ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
        return None

    def __repr__(self):
        return f'<Patient MRN: {self.mrn} - {self.first_name} {self.last_name}>'


class PatientAllergy(db.Model):
    __tablename__ = 'patient_allergies'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False)
    allergen_name = db.Column(db.String(255), nullable=False)
    reaction_description = db.Column(db.Text, nullable=True)
    severity = db.Column(db.String(50), default='Unknown')
    recorded_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    is_active = db.Column(db.Boolean, default=True)

class ClinicalNote(db.Model):
    __tablename__ = 'clinical_notes'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False)
    author_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    note_type = db.Column(db.String(100), nullable=False)
    service_specialty = db.Column(db.String(100), nullable=True)
    title = db.Column(db.String(255), nullable=True)
    content_text = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='Draft')
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    signed_at = db.Column(db.DateTime, nullable=True)
    signed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    co_signed_at = db.Column(db.DateTime, nullable=True)
    co_signed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

class PatientProblemList(db.Model):
    __tablename__ = 'patient_problem_list'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False)
    icd10_code = db.Column(db.String(20), nullable=True)
    problem_description = db.Column(db.Text, nullable=False)
    onset_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(50), default='Active')
    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    recorded_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class OrderableItem(db.Model): 
    __tablename__ = 'orderable_items'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    item_type = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(255), nullable=False, index=True)
    generic_name = db.Column(db.String(255), nullable=True)
    code = db.Column(db.String(50), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    parent_id = db.Column(db.String(36), db.ForeignKey('orderable_items.id'), nullable=True)

    parent = db.relationship(
    'OrderableItem',
    remote_side=[id],
    backref=db.backref('children', lazy='joined'),
    lazy='joined'
)



class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False)
    orderable_item_id = db.Column(db.String(36), db.ForeignKey('orderable_items.id'), nullable=False)
    order_details = db.Column(db.JSON, nullable=True)
    priority = db.Column(db.String(50), default='Routine')  # Options: Stat, Urgent, Routine, Low
    status = db.Column(db.String(50), default='Draft')  # Draft, Placed, In Progress, Completed, Discontinued

    ordering_physician_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    order_placed_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    signed_at = db.Column(db.DateTime, nullable=True)
    signed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    discontinued_at = db.Column(db.DateTime, nullable=True)
    discontinued_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    discontinuation_reason = db.Column(db.Text, nullable=True)

    # Optional enhancements
    reviewed_by_nurse_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    administration_instructions = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_critical = db.Column(db.Boolean, default=False)

    # Relationships
    orderable_item = db.relationship('OrderableItem', backref='orders')
    ordering_physician = db.relationship('User', foreign_keys=[ordering_physician_id])
    signed_by = db.relationship('User', foreign_keys=[signed_by_user_id])
    discontinued_by = db.relationship('User', foreign_keys=[discontinued_by_user_id])
    reviewed_by_nurse = db.relationship('User', foreign_keys=[reviewed_by_nurse_id])

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "orderable_item_id": self.orderable_item_id,
            "order_details": self.order_details,
            "priority": self.priority,
            "status": self.status,
            "ordering_physician_id": self.ordering_physician_id,
            "order_placed_at": self.order_placed_at.isoformat() if self.order_placed_at else None,
            "signed_at": self.signed_at.isoformat() if self.signed_at else None,
            "signed_by_user_id": self.signed_by_user_id,
            "discontinued_at": self.discontinued_at.isoformat() if self.discontinued_at else None,
            "discontinued_by_user_id": self.discontinued_by_user_id,
            "discontinuation_reason": self.discontinuation_reason,
            "reviewed_by_nurse_id": self.reviewed_by_nurse_id,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "administration_instructions": self.administration_instructions,
            "notes": self.notes,
            "is_critical": self.is_critical
        }


class PatientMedication(db.Model):
    __tablename__ = 'patient_medications'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False, index=True)
    orderable_item_id = db.Column(db.String(36), db.ForeignKey('orderable_items.id'), nullable=True) # If from formulary
    medication_name = db.Column(db.String(255), nullable=False) # Free text if not from formulary or for home med
    
    type = db.Column(db.String(50), nullable=False, index=True) # e.g., 'INPATIENT_ACTIVE', 'HOME_MED', 'DISCHARGE_MED'
    
    dose = db.Column(db.String(100), nullable=True)
    route = db.Column(db.String(50), nullable=True)
    frequency = db.Column(db.String(100), nullable=True)
    prn_reason = db.Column(db.String(255), nullable=True)
    indication = db.Column(db.String(255), nullable=True)

    start_datetime = db.Column(db.DateTime, default=datetime.datetime.utcnow) # Renamed from start_date for clarity
    end_datetime = db.Column(db.DateTime, nullable=True) # Renamed from end_date
    status = db.Column(db.String(50), default='Active', index=True) # Active, Discontinued, Held, Completed (for courses)

    # For home medications
    source_of_information = db.Column(db.String(100), nullable=True)
    last_taken_datetime = db.Column(db.DateTime, nullable=True)

    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # Nullable if system generated
    recorded_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    source_order_id = db.Column(db.String(36), db.ForeignKey('orders.id'), nullable=True) # If originated from an order

    # Relationships
    patient = db.relationship('Patient', backref=db.backref('medications', lazy='dynamic'))
    orderable_item = db.relationship('OrderableItem', foreign_keys=[orderable_item_id]) # Renamed for clarity
    recorded_by = db.relationship('User', foreign_keys=[recorded_by_user_id])
    source_order = db.relationship('Order', foreign_keys=[source_order_id])

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "orderable_item_id": self.orderable_item_id,
            "medication_name": self.medication_name or (self.orderable_item.name if self.orderable_item else None),
            "type": self.type,
            "dose": self.dose,
            "route": self.route,
            "frequency": self.frequency,
            "prn_reason": self.prn_reason,
            "indication": self.indication,
            "start_datetime": self.start_datetime.isoformat() if self.start_datetime else None,
            "end_datetime": self.end_datetime.isoformat() if self.end_datetime else None,
            "status": self.status,
            "source_of_information": self.source_of_information,
            "last_taken_datetime": self.last_taken_datetime.isoformat() if self.last_taken_datetime else None,
            "recorded_by_user_id": self.recorded_by_user_id,
            "recorded_by_username": self.recorded_by.username if self.recorded_by else None,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "source_order_id": self.source_order_id
        }

    def __repr__(self):
        return f'<PatientMedication {self.id} - {self.medication_name} for Patient {self.patient_id}>'


class MedicationReconciliationLog(db.Model):
    __tablename__ = 'medication_reconciliation_logs'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False, index=True)
    reconciliation_type = db.Column(db.String(50), nullable=False, index=True) # ADMISSION, TRANSFER, DISCHARGE
    reconciled_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reconciliation_datetime = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    # Example decision: {"patient_medication_id": "uuid_of_PatientMed_entry", "action": "CONTINUE/DISCONTINUE/MODIFY", "new_dose": "...", "comment": "..."}
    # Or, if reconciling against an external list: {"external_med_name": "Lisinopril", "action": "ADD_TO_HOME_MEDS", ...}
    decisions_log = db.Column(db.JSON, nullable=True) 
    notes = db.Column(db.Text, nullable=True)

    # Relationships
    patient = db.relationship('Patient', backref=db.backref('med_reconciliation_logs', lazy='dynamic'))
    reconciled_by = db.relationship('User', foreign_keys=[reconciled_by_user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "reconciliation_type": self.reconciliation_type,
            "reconciled_by_user_id": self.reconciled_by_user_id,
            "reconciled_by_username": self.reconciled_by.username if self.reconciled_by else None,
            "reconciliation_datetime": self.reconciliation_datetime.isoformat() if self.reconciliation_datetime else None,
            "decisions_log": self.decisions_log,
            "notes": self.notes
        }

    def __repr__(self):
        return f'<MedicationReconciliationLog {self.id} for Patient {self.patient_id} at {self.reconciliation_datetime}>'


class LabResult(db.Model):
    __tablename__ = 'lab_results'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False)
    ordered_test_id = db.Column(db.String(36), db.ForeignKey('orderable_items.id'), nullable=True) 
    
    test_name = db.Column(db.String(255), nullable=False)
    panel_name = db.Column(db.String(255), nullable=True)
    
    value = db.Column(db.String(100))
    value_numeric = db.Column(db.Float, nullable=True)
    units = db.Column(db.String(50))
    reference_range = db.Column(db.String(100))
    
    abnormal_flag = db.Column(db.String(20), nullable=True)
    status = db.Column(db.String(50), default='Preliminary')
    
    collection_datetime = db.Column(db.DateTime, nullable=False)
    result_datetime = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    performing_lab = db.Column(db.String(100), nullable=True)
    
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    acknowledged_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    patient = db.relationship('Patient', backref='lab_results_data', lazy=True) # Changed backref to avoid conflict with relationship name
    acknowledged_by = db.relationship('User', foreign_keys=[acknowledged_by_user_id])

    # --- ADD THIS METHOD ---
    def to_dict(self):
        """Serializes the LabResult object to a dictionary."""
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "ordered_test_id": self.ordered_test_id,
            "test_name": self.test_name,
            "panel_name": self.panel_name,
            "value": self.value,
            "value_numeric": self.value_numeric,
            "units": self.units,
            "reference_range": self.reference_range,
            "abnormal_flag": self.abnormal_flag,
            "status": self.status,
            "collection_datetime": self.collection_datetime.isoformat() if self.collection_datetime else None,
            "result_datetime": self.result_datetime.isoformat() if self.result_datetime else None,
            "performing_lab": self.performing_lab,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "acknowledged_by_user_id": self.acknowledged_by_user_id,
            "acknowledged_by_username": self.acknowledged_by.username if self.acknowledged_by else None
        }
def __repr__(self):
        return f'<LabResult {self.id} | {self.test_name} for Patient {self.patient_id}>'

class ImagingReport(db.Model):
    __tablename__ = 'imaging_reports'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False)
    ordered_study_id = db.Column(db.String(36), db.ForeignKey('orderable_items.id'), nullable=True)
    
    modality = db.Column(db.String(50), nullable=False) # XRAY, CT, MRI, US, ECHO
    study_description = db.Column(db.String(255), nullable=False)
    study_datetime = db.Column(db.DateTime, nullable=False)
    
    report_text = db.Column(db.Text) # Full report text including impressions and findings
    impression_text = db.Column(db.Text, nullable=True) # Key impressions for quick view
    
    status = db.Column(db.String(50), default='Preliminary') # Preliminary, Final, Addendum
    reported_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # Radiologist
    report_datetime = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    acknowledged_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Relationships
    patient = db.relationship('Patient', backref='imaging_reports_data', lazy=True) # Changed backref to avoid conflict
    reported_by = db.relationship('User', foreign_keys=[reported_by_user_id])
    acknowledged_by = db.relationship('User', foreign_keys=[acknowledged_by_user_id])
    orderable_item = db.relationship('OrderableItem') # For getting original order info

    def to_dict(self):
        """Serializes the ImagingReport object to a dictionary."""
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "ordered_study_id": self.ordered_study_id,
            "modality": self.modality,
            "study_description": self.study_description,
            "study_datetime": self.study_datetime.isoformat() if self.study_datetime else None,
            "report_text": self.report_text,
            "impression_text": self.impression_text,
            "status": self.status,
            "reported_by_user_id": self.reported_by_user_id,
            "reported_by_username": self.reported_by.username if self.reported_by else None,
            "report_datetime": self.report_datetime.isoformat() if self.report_datetime else None,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "acknowledged_by_user_id": self.acknowledged_by_user_id,
            "acknowledged_by_username": self.acknowledged_by.username if self.acknowledged_by else None
        }

    def __repr__(self):
        return f'<ImagingReport {self.id} for Patient {self.patient_id}>'
    
class CDSRule(db.Model):
    __tablename__ = 'cds_rules'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    rule_name = db.Column(db.String(255), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    # e.g., "DrugInteraction", "AllergyCheck", "DoseRange", "DuplicateOrder", "GuidelineReminder"
    rule_type = db.Column(db.String(100), nullable=False, index=True)
    # JSONB is great for storing flexible rule criteria, actions, messages, severity, etc.
    rule_logic = db.Column(db.JSON, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def to_dict(self):
        """Serializes the CDSRule object to a dictionary."""
        return {
            "id": self.id,
            "rule_name": self.rule_name,
            "description": self.description,
            "rule_type": self.rule_type,
            "rule_logic": self.rule_logic,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

    def __repr__(self):
        return f'<CDSRule {self.rule_name} ({self.rule_type})>'

class Task(db.Model):
    __tablename__ = 'tasks'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=True, index=True) 
    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) 
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    due_datetime = db.Column(db.DateTime, nullable=True)
    
    completed = db.Column(db.Boolean, default=False, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    priority = db.Column(db.String(50), default='Normal') # e.g., Low, Normal, High, Urgent
    category = db.Column(db.String(100), nullable=True) # e.g., "Labs Review", "Consult", "Documentation"
    department = db.Column(db.String(100), nullable=True) # e.g., "Cardiology", "ICU"
    status = db.Column(db.String(50), default='Pending') # Pending, In Progress, Completed, Cancelled
    is_urgent = db.Column(db.Boolean, default=False)
    visibility = db.Column(db.String(50), default='private') # e.g., private (to assignee/creator), team, public (within role)

    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


    # Relationships
    # Ensure backref names are unique if 'tasks' is used elsewhere for Patient or User
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_user_id], backref=db.backref('assigned_tasks', lazy='dynamic'))
    created_by = db.relationship('User', foreign_keys=[created_by_user_id], backref=db.backref('created_tasks', lazy='dynamic'))

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "description": self.description,
            "due_datetime": self.due_datetime.isoformat() if self.due_datetime else None,
            "patient_id": self.patient_id,
            "assigned_to_user_id": self.assigned_to_user_id,
            "assigned_to_username": self.assigned_to.username if self.assigned_to else None,
            "created_by_user_id": self.created_by_user_id,
            "created_by_username": self.created_by.username if self.created_by else None,
            "priority": self.priority, "category": self.category, "department": self.department,
            "status": self.status, "completed": self.completed,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "is_urgent": self.is_urgent, "visibility": self.visibility,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


    def __repr__(self):
        return f'<Task {self.id} - {self.title}>'

class VitalSign(db.Model):
    __tablename__ = 'vital_signs'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False, index=True)
    recorded_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Standard Vitals
    temperature_celsius = db.Column(db.Float, nullable=True)
    heart_rate_bpm = db.Column(db.Integer, nullable=True)
    respiratory_rate_rpm = db.Column(db.Integer, nullable=True)
    systolic_bp_mmhg = db.Column(db.Integer, nullable=True)
    diastolic_bp_mmhg = db.Column(db.Integer, nullable=True)
    oxygen_saturation_percent = db.Column(db.Float, nullable=True)
    pain_score_0_10 = db.Column(db.Integer, nullable=True)

    # Additional Measurements
    weight_kg = db.Column(db.Float, nullable=True)
    height_cm = db.Column(db.Float, nullable=True)
    blood_glucose_mg_dl = db.Column(db.Integer, nullable=True)
    blood_glucose_mmol_l = db.Column(db.Float, nullable=True) # Consider storing one and converting
    blood_glucose_type = db.Column(db.String(50), nullable=True) # e.g., "Fasting", "Random"

    # Contextual Information
    consciousness_level = db.Column(db.String(100), nullable=True) # e.g., "Alert", "AVPU", "GCS details"
    patient_position = db.Column(db.String(50), nullable=True)
    activity_level = db.Column(db.String(50), nullable=True)
    o2_therapy_device = db.Column(db.String(100), nullable=True)
    o2_flow_rate_lpm = db.Column(db.Float, nullable=True)
    fio2_percent = db.Column(db.Float, nullable=True)

    # Specific lab/clinical markers relevant to some scores (often from LabResult model, but can be here if point-of-care)
    troponin_ng_l = db.Column(db.Float, nullable=True) # Example, usually a lab result
    creatinine_umol_l = db.Column(db.Float, nullable=True) # Example, usually a lab result
    ecg_changes = db.Column(db.String(200), nullable=True) # e.g. "ST Elevation in V1-V3"

    notes = db.Column(db.Text, nullable=True)

    # Relationships
    patient = db.relationship('Patient', backref=db.backref('vital_signs_entries', lazy='dynamic', order_by="desc(VitalSign.recorded_at)"))
    recorded_by = db.relationship('User', foreign_keys=[recorded_by_user_id])

    @property
    def bmi(self):
        if self.height_cm and self.weight_kg and self.height_cm > 0:
            return round(self.weight_kg / ((self.height_cm / 100) ** 2), 2)
        return None

    @property
    def bp_category(self):
        if self.systolic_bp_mmhg and self.diastolic_bp_mmhg:
            s, d = self.systolic_bp_mmhg, self.diastolic_bp_mmhg
            if s >= 180 or d >= 120: return "Hypertensive Crisis"
            if s >= 140 or d >= 90: return "Hypertension Stage 2"
            if s >= 130 or d >= 80: return "Hypertension Stage 1"
            if s >= 120: return "Elevated"
            if s < 90 or d < 60 : return "Hypotension" # Added for completeness
            return "Normal"
        return None

    @property
    def qsofa_score(self):
        # Requires: respiratory_rate_rpm, systolic_bp_mmhg, consciousness_level
        score = 0
        if self.respiratory_rate_rpm and self.respiratory_rate_rpm >= 22: score += 1
        if self.systolic_bp_mmhg and self.systolic_bp_mmhg <= 100: score += 1
        # Assuming 'alert' is the baseline for consciousness_level
        if self.consciousness_level and self.consciousness_level.lower() not in ['alert', 'a (alert)']: score += 1
        return score

    @property
    def mews_score(self): # Modified Early Warning Score
        score = 0
        # Heart Rate
        if self.heart_rate_bpm is not None:
            if self.heart_rate_bpm <= 40: score += 2
            elif 41 <= self.heart_rate_bpm <= 50: score += 1
            elif 101 <= self.heart_rate_bpm <= 110: score += 1
            elif 111 <= self.heart_rate_bpm <= 129: score += 2
            elif self.heart_rate_bpm >= 130: score += 3
        # Systolic BP
        if self.systolic_bp_mmhg is not None:
            if self.systolic_bp_mmhg <= 70: score += 3
            elif 71 <= self.systolic_bp_mmhg <= 80: score += 2
            elif 81 <= self.systolic_bp_mmhg <= 100: score += 1
            elif self.systolic_bp_mmhg >= 200: score += 2 # Some MEWS include high BP
        # Respiratory Rate
        if self.respiratory_rate_rpm is not None:
            if self.respiratory_rate_rpm < 9: score += 2
            elif 15 <= self.respiratory_rate_rpm <= 20: score += 0 # Baseline for some scales
            elif 21 <= self.respiratory_rate_rpm <= 29: score += 2
            elif self.respiratory_rate_rpm >= 30: score += 3
        # Temperature
        if self.temperature_celsius is not None:
            if self.temperature_celsius <= 35.0: score += 2
            elif self.temperature_celsius >= 38.5: score += 2
        # Consciousness Level (AVPU mapping to score)
        if self.consciousness_level:
            level = self.consciousness_level.lower()
            if level == 'v (voice)' or 'voice' in level: score += 1
            elif level == 'p (pain)' or 'pain' in level: score += 2
            elif level == 'u (unresponsive)' or 'unresponsive' in level: score += 3
            # 'A (Alert)' is 0 points
        return score

    @property
    def cha2ds2_vasc_score(self):
        # This score RELIES on patient history from the Patient model
        if not self.patient: return None # Cannot calculate without patient context
        
        score = 0
        patient_age = self.patient.age # Uses the @property age from Patient model
        
        if self.patient.congestive_heart_failure: score += 1
        if self.patient.hypertension: score += 1
        if patient_age is not None:
            if patient_age >= 75: score += 2
            elif 65 <= patient_age <= 74: score += 1
        if self.patient.diabetes: score += 1
        if self.patient.stroke_or_tia: score += 2 # Previous Stroke/TIA/Thromboembolism
        if self.patient.vascular_disease: score += 1 # e.g. MI, PAD, Aortic plaque
        if self.patient.gender and self.patient.gender.lower() == 'female': score += 1
        # Atrial Fibrillation is often a prerequisite for using CHA2DS2-VASc,
        # but sometimes included in risk if not the primary indication.
        # For this score, it's usually assumed the patient has AFib.
        # If self.patient.atrial_fibrillation: score += 1 # (This is not standard in the score itself but a common context)
        return score

    @property
    def timi_score_ua_nstemi(self): # TIMI Risk Score for UA/NSTEMI
        # This score RELIES on patient history and some current findings
        if not self.patient: return None

        score = 0
        patient_age = self.patient.age

        if patient_age is not None and patient_age >= 65: score += 1
        # >= 3 CAD risk factors (FHx CAD, HTN, HLD, DM, active smoker)
        # This requires more detailed patient history than we currently model directly.
        # For a simplified version, we'll count the ones we have:
        risk_factors = 0
        if self.patient.hypertension: risk_factors +=1
        if self.patient.diabetes: risk_factors +=1
        # if self.patient.hyperlipidemia: risk_factors +=1 # Needs Patient model update
        # if self.patient.smoker: risk_factors +=1 # Needs Patient model update
        # if self.patient.family_history_cad: risk_factors +=1 # Needs Patient model update
        if risk_factors >= 1: # Simplified: presence of any of these is one point for this factor
             # The actual TIMI score counts >=3 of the standard 5 risk factors as 1 point.
             # This is a simplification.
             pass # Placeholder for more complex risk factor counting

        if self.patient.known_cad: score += 1 # Known CAD (stenosis >= 50%)
        # Aspirin use in past 7 days - needs medication history
        # if self.patient.used_aspirin_last_7_days: score += 1 # Needs Patient model update or med history check

        # Severe angina (>=2 episodes in 24h) - needs to be captured, perhaps in notes or a specific field
        # if self.recent_severe_angina: score += 1

        if self.ecg_changes and ("st deviation" in self.ecg_changes.lower() or "st depression" in self.ecg_changes.lower()):
            score += 1 # ST deviation >= 0.5 mm
        
        if self.troponin_ng_l is not None: # Assuming troponin is elevated (exact threshold varies)
            # Example: if self.troponin_ng_l > (upper_limit_of_normal * 1.5): # Needs lab reference
            # For simplicity, if any troponin is recorded and > 0 (assuming ng/L can't be negative)
            if self.troponin_ng_l > 0.04: # Example threshold for high sensitivity troponin
                score += 1 # Positive cardiac marker
        
        return score


    def to_dict(self):
        # Base dictionary
        data = {
            "id": self.id,
            "patient_id": self.patient_id,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "recorded_by_user_id": self.recorded_by_user_id,
            "recorded_by_username": self.recorded_by.username if self.recorded_by else None,
            "temperature_celsius": self.temperature_celsius,
            "heart_rate_bpm": self.heart_rate_bpm,
            "respiratory_rate_rpm": self.respiratory_rate_rpm,
            "systolic_bp_mmhg": self.systolic_bp_mmhg,
            "diastolic_bp_mmhg": self.diastolic_bp_mmhg,
            "oxygen_saturation_percent": self.oxygen_saturation_percent,
            "pain_score_0_10": self.pain_score_0_10,
            "weight_kg": self.weight_kg,
            "height_cm": self.height_cm,
            "blood_glucose_mg_dl": self.blood_glucose_mg_dl,
            "blood_glucose_mmol_l": self.blood_glucose_mmol_l,
            "blood_glucose_type": self.blood_glucose_type,
            "consciousness_level": self.consciousness_level,
            "patient_position": self.patient_position,
            "activity_level": self.activity_level,
            "o2_therapy_device": self.o2_therapy_device,
            "o2_flow_rate_lpm": self.o2_flow_rate_lpm,
            "fio2_percent": self.fio2_percent,
            "troponin_ng_l": self.troponin_ng_l,
            "creatinine_umol_l": self.creatinine_umol_l,
            "ecg_changes": self.ecg_changes,
            "notes": self.notes,
        }
        # Add calculated properties
        data["bmi"] = self.bmi
        data["bp_category"] = self.bp_category
        data["qsofa_score"] = self.qsofa_score
        data["mews_score"] = self.mews_score
        if self.patient: # Ensure patient context exists for these scores
            data["cha2ds2_vasc_score"] = self.cha2ds2_vasc_score
            data["timi_score_ua_nstemi"] = self.timi_score_ua_nstemi
        else:
            data["cha2ds2_vasc_score"] = None
            data["timi_score_ua_nstemi"] = None
            
        return data

    def __repr__(self):
        return f'<VitalSign {self.id} for Patient {self.patient_id} at {self.recorded_at}>'


class RoundingNote(db.Model):
    __tablename__ = 'rounding_notes'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False)
    rounding_physician_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rounding_datetime = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    subjective = db.Column(db.Text, nullable=True)
    objective = db.Column(db.Text, nullable=True)
    assessment = db.Column(db.Text, nullable=True)
    plan = db.Column(db.Text, nullable=True)

    # Enhancements:
    is_finalized = db.Column(db.Boolean, default=False)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    priority = db.Column(db.String(20), nullable=True)  # e.g., "Low", "Medium", "High"
    duration_minutes = db.Column(db.Integer, nullable=True)
    location = db.Column(db.String(100), nullable=True)

    patient = db.relationship('Patient', backref='rounding_notes')
    physician = db.relationship('User', foreign_keys=[rounding_physician_id])
    reviewer = db.relationship('User', foreign_keys=[reviewed_by_id])

    def __repr__(self):
        return f'<RoundingNote {self.id} for Patient {self.patient_id} by Physician {self.rounding_physician_id}>'



class DischargePlan(db.Model):
    __tablename__ = 'discharge_plans'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # Made nullable, creator might be system or set later

    discharge_goals = db.Column(db.Text, nullable=True)
    followup_plan = db.Column(db.Text, nullable=True) # Could store structured appointment data here or link to a separate model
    discharge_medications_summary = db.Column(db.Text, nullable=True) # Summary; actual med reconciliation is separate
    discharge_needs = db.Column(db.Text, nullable=True)  # e.g., PT, home oxygen, home health
    anticipated_discharge_date = db.Column(db.DateTime, nullable=True)

    # Fields from your model definition
    barriers_to_discharge = db.Column(db.Text, nullable=True)
    family_or_caregiver_notes = db.Column(db.Text, nullable=True) # Can also cover social support status
    transportation_needs = db.Column(db.String(100), nullable=True)
    home_environment_safety_notes = db.Column(db.Text, nullable=True) # Renamed from home_environment_assessment for clarity
    post_discharge_instructions = db.Column(db.Text, nullable=True) # Covers education_provided and discharge_instructions
    equipment_needed = db.Column(db.Text, nullable=True)

    # Consult flags from your model
    social_work_consult_ordered = db.Column(db.Boolean, default=False)
    case_management_consult_ordered = db.Column(db.Boolean, default=False)
    physical_therapy_consult_ordered = db.Column(db.Boolean, default=False)
    occupational_therapy_consult_ordered = db.Column(db.Boolean, default=False)
    speech_therapy_consult_ordered = db.Column(db.Boolean, default=False)
    nutrition_consult_ordered = db.Column(db.Boolean, default=False)
    
    # Additional summary fields from your route logic if distinct
    nursing_summary = db.Column(db.Text, nullable=True)
    therapy_summary = db.Column(db.Text, nullable=True) # Could be PT/OT/Speech combined or separate
    care_coordination_notes = db.Column(db.Text, nullable=True)


    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    patient = db.relationship('Patient', backref=db.backref('all_discharge_plans', lazy='dynamic', order_by="desc(DischargePlan.created_at)"))
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])

    def to_dict(self): # Converted to instance method
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "patient_name": f"{self.patient.first_name} {self.patient.last_name}" if self.patient else None,
            "created_by_user_id": self.created_by_user_id,
            "created_by_username": self.created_by.username if self.created_by else None,
            "discharge_goals": self.discharge_goals,
            "followup_plan": self.followup_plan,
            "discharge_medications_summary": self.discharge_medications_summary,
            "discharge_needs": self.discharge_needs,
            "anticipated_discharge_date": self.anticipated_discharge_date.isoformat() if self.anticipated_discharge_date else None,
            "barriers_to_discharge": self.barriers_to_discharge,
            "family_or_caregiver_notes": self.family_or_caregiver_notes,
            "transportation_needs": self.transportation_needs,
            "home_environment_safety_notes": self.home_environment_safety_notes,
            "post_discharge_instructions": self.post_discharge_instructions,
            "equipment_needed": self.equipment_needed,
            "social_work_consult_ordered": self.social_work_consult_ordered,
            "case_management_consult_ordered": self.case_management_consult_ordered,
            "physical_therapy_consult_ordered": self.physical_therapy_consult_ordered,
            "occupational_therapy_consult_ordered": self.occupational_therapy_consult_ordered,
            "speech_therapy_consult_ordered": self.speech_therapy_consult_ordered,
            "nutrition_consult_ordered": self.nutrition_consult_ordered,
            "nursing_summary": self.nursing_summary,
            "therapy_summary": self.therapy_summary,
            "care_coordination_notes": self.care_coordination_notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

    def __repr__(self):
        return f'<DischargePlan {self.id} for Patient {self.patient_id}>'

class PatientFlag(db.Model):
    __tablename__ = 'patient_flags'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False, index=True)
    flagged_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    flag_type = db.Column(db.String(100), nullable=False, index=True)  # Increased length for more descriptive types
    severity = db.Column(db.String(50), nullable=True)   # e.g., "Low", "Moderate", "High", "Critical"
    notes = db.Column(db.Text, nullable=True)
    
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    expires_at = db.Column(db.DateTime, nullable=True) # Optional: for flags that might be temporary
    
    # Review tracking for flags
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)

    # Relationships
    patient = db.relationship('Patient', backref=db.backref('all_flags', lazy='dynamic', order_by="desc(PatientFlag.created_at)"))
    flagged_by = db.relationship('User', foreign_keys=[flagged_by_user_id], backref=db.backref('created_flags', lazy='dynamic'))
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_user_id], backref=db.backref('reviewed_flags', lazy='dynamic'))

    def mark_reviewed(self, reviewer_id, notes=None):
        self.reviewed_by_user_id = reviewer_id
        self.reviewed_at = datetime.datetime.utcnow()
        if notes:
            self.review_notes = notes
        self.updated_at = datetime.datetime.utcnow() # Also update this when reviewed
        db.session.add(self) # Ensure change is staged

    def deactivate(self):
        self.is_active = False
        self.updated_at = datetime.datetime.utcnow()
        db.session.add(self) # Ensure change is staged

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "patient_name": f"{self.patient.first_name} {self.patient.last_name}" if self.patient else None,
            "flagged_by_user_id": self.flagged_by_user_id,
            "flagged_by_username": self.flagged_by.username if self.flagged_by else None,
            "flag_type": self.flag_type,
            "severity": self.severity,
            "notes": self.notes,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "reviewed_by_user_id": self.reviewed_by_user_id,
            "reviewed_by_username": self.reviewed_by.username if self.reviewed_by else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "review_notes": self.review_notes
        }

    def __repr__(self):
        return f'<PatientFlag {self.flag_type} (Severity: {self.severity}) for Patient {self.patient_id}>'
    
class HandoffEntry(db.Model):
    __tablename__ = 'handoff_entries'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False, index=True)
    written_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    written_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    
    # Core clinical info
    current_condition = db.Column(db.Text, nullable=True)
    active_issues = db.Column(db.Text, nullable=True) # Could be structured (e.g., JSON array of strings)
    overnight_events = db.Column(db.Text, nullable=True) # Or events during the shift
    anticipatory_guidance = db.Column(db.Text, nullable=True) # What to watch out for
    plan_for_next_shift = db.Column(db.Text, nullable=True) # Renamed from plan_for_today for clarity
    
    # New fields for enhanced functionality from your model
    vital_signs_summary = db.Column(db.Text, nullable=True)
    medications_changes_summary = db.Column(db.Text, nullable=True) # Summary of med changes
    labs_pending_summary = db.Column(db.Text, nullable=True)
    consults_pending_summary = db.Column(db.Text, nullable=True)
    
    # These might be better dynamically fetched from Patient model or latest records to avoid stale data
    # For now, including as per your model, but consider if these should be snapshots or live data links
    allergies_summary_at_handoff = db.Column(db.Text, nullable=True) 
    code_status_at_handoff = db.Column(db.String(50), nullable=True)
    isolation_precautions_at_handoff = db.Column(db.String(100), nullable=True)
    
    handoff_priority = db.Column(db.String(50), nullable=True, default='Normal') # e.g., High, Medium, Normal
    
    # Track updates and review
    last_updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)
    
    # Relationships
    patient = db.relationship('Patient', backref=db.backref('all_handoff_entries', lazy='dynamic', order_by="desc(HandoffEntry.written_at)"))
    written_by = db.relationship('User', foreign_keys=[written_by_user_id], backref=db.backref('authored_handoff_entries', lazy='dynamic'))
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_user_id], backref=db.backref('reviewed_handoff_entries', lazy='dynamic'))

    def mark_reviewed(self, reviewer_id, notes=None):
        self.reviewed_by_user_id = reviewer_id
        self.reviewed_at = datetime.datetime.utcnow()
        if notes:
            self.review_notes = notes
        db.session.add(self) # Ensure change is staged for commit
        # Commit should happen in the route after calling this

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "patient_name": f"{self.patient.first_name} {self.patient.last_name}" if self.patient else None,
            "written_by_user_id": self.written_by_user_id,
            "written_by_username": self.written_by.username if self.written_by else None,
            "written_at": self.written_at.isoformat() if self.written_at else None,
            "current_condition": self.current_condition,
            "active_issues": self.active_issues,
            "overnight_events": self.overnight_events,
            "anticipatory_guidance": self.anticipatory_guidance,
            "plan_for_next_shift": self.plan_for_next_shift,
            "vital_signs_summary": self.vital_signs_summary,
            "medications_changes_summary": self.medications_changes_summary,
            "labs_pending_summary": self.labs_pending_summary,
            "consults_pending_summary": self.consults_pending_summary,
            "allergies_summary_at_handoff": self.allergies_summary_at_handoff,
            "code_status_at_handoff": self.code_status_at_handoff,
            "isolation_precautions_at_handoff": self.isolation_precautions_at_handoff,
            "handoff_priority": self.handoff_priority,
            "last_updated_at": self.last_updated_at.isoformat() if self.last_updated_at else None,
            "reviewed_by_user_id": self.reviewed_by_user_id,
            "reviewed_by_username": self.reviewed_by.username if self.reviewed_by else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "review_notes": self.review_notes
        }
class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Core Relationships
    recipient_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    related_patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=True, index=True) # Added index

    # Notification Content
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(
        db.String(100), 
        nullable=False, 
        index=True, 
        comment="E.g., CRITICAL_LAB, TASK_DUE, NEW_CONSULT, ORDER_SIGN"
    )
    
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)

    # Optional: Smart Linking to Specific Chart Elements
    link_to_item_type = db.Column(
        db.String(50), 
        nullable=True, 
        comment="E.g., 'Patient', 'Order', 'Task', 'LabResult'"
    )
    link_to_item_id = db.Column(db.String(36), nullable=True)

    # Optional: Allow richer linking context (future extensibility)
    metadata_json = db.Column(db.JSON, nullable=True, comment="Optional structured payload for frontend logic")

    # Optional: Urgency flag for UI badge/highlight (non-blocking)
    is_urgent = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    recipient = db.relationship(
        'User', 
        backref=db.backref('all_notifications', lazy='dynamic', order_by="desc(Notification.created_at)") # Renamed backref for clarity
    )
    # Ensure Patient model is imported if not already via other relationships
    related_patient = db.relationship('Patient', foreign_keys=[related_patient_id], backref=db.backref('related_notifications', lazy='dynamic'))


    def to_dict(self):
        return {
            "id": self.id,
            "recipient_user_id": self.recipient_user_id,
            "message": self.message,
            "notification_type": self.notification_type,
            "is_read": self.is_read,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "link_to_item_type": self.link_to_item_type,
            "link_to_item_id": self.link_to_item_id,
            "related_patient_id": self.related_patient_id,
            "related_patient_name": (
                f"{self.related_patient.first_name} {self.related_patient.last_name}"
                if self.related_patient else None
            ),
            "metadata_json": self.metadata_json,
            "is_urgent": self.is_urgent
        }

    def __repr__(self):
        return (
            f"<Notification {self.id} | User: {self.recipient_user_id} | "
            f"Type: {self.notification_type} | Urgent: {self.is_urgent}>"
        )
    def __repr__(self):
        return f'<HandoffEntry {self.id} for Patient {self.patient_id}>'
    
user_group_members = db.Table('user_group_members',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('group_id', db.String(36), db.ForeignKey('user_groups.id'), primary_key=True)
)


class UserGroup(db.Model):
    __tablename__ = 'user_groups'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    # Relationship to User model for members
    # The backref 'member_of_groups' will allow you to do user_instance.member_of_groups
    members = db.relationship('User', secondary=user_group_members, lazy='dynamic',
                              backref=db.backref('user_groups_membership', lazy='dynamic')) # Changed backref name for clarity

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "member_count": self.members.count() # Example of a useful derived property
        }

    def __repr__(self):
        return f'<UserGroup {self.name}>'
class Appointment(db.Model):
    __tablename__ = 'appointments'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    patient_id = db.Column(db.String(36), db.ForeignKey('patients.id'), nullable=False, index=True)
    provider_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True) # This is the doctor/clinician
    
    start_datetime = db.Column(db.DateTime, nullable=False, index=True)
    end_datetime = db.Column(db.DateTime, nullable=False) # Duration can be derived, but explicit end is often useful
    
    appointment_type = db.Column(db.String(100), nullable=True) # e.g., "New Patient Visit", "Follow-up", "Annual Physical", "Procedure"
    
    status = db.Column(
        db.String(50), 
        nullable=False, 
        default='Scheduled', 
        index=True,
        comment="Valid values: Scheduled, Confirmed, CancelledByPatient, CancelledByClinic, Completed, NoShow, Rescheduled"
    )
    
    location = db.Column(db.String(255), nullable=True) # e.g., "Clinic A, Room 101", "Telehealth"
    reason_for_visit = db.Column(db.Text, nullable=True) # Patient's stated reason
    notes = db.Column(db.Text, nullable=True) # Internal notes for the appointment
    
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # User who booked it (scheduler, staff, or patient via portal)
    
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    patient = db.relationship(
        'Patient', 
        backref=db.backref('patient_appointments', lazy='dynamic', order_by="desc(Appointment.start_datetime)") # Specific backref name
    )
    provider = db.relationship(
        'User', 
        foreign_keys=[provider_user_id], 
        backref=db.backref('provider_appointments', lazy='dynamic') # Specific backref name
    )
    created_by = db.relationship(
        'User', 
        foreign_keys=[created_by_user_id],
        backref=db.backref('appointments_created_by_user', lazy='dynamic') # Specific backref name
    )

    def to_dict(self, include_related=True):
        data = {
            "id": self.id,
            "patient_id": self.patient_id,
            "provider_user_id": self.provider_user_id,
            "start_datetime": self.start_datetime.isoformat() if self.start_datetime else None,
            "end_datetime": self.end_datetime.isoformat() if self.end_datetime else None,
            "appointment_type": self.appointment_type,
            "status": self.status,
            "location": self.location,
            "reason_for_visit": self.reason_for_visit,
            "notes": self.notes,
            "created_by_user_id": self.created_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_related:
            if self.patient:
                data["patient_name"] = f"{self.patient.first_name} {self.patient.last_name}"
                data["patient_mrn"] = self.patient.mrn
            if self.provider:
                data["provider_name"] = self.provider.full_name # Assuming User model has full_name
            if self.created_by:
                data["created_by_username"] = self.created_by.username
        return data

    def __repr__(self):
        return (
            f"<Appointment {self.id} | Patient {self.patient_id} | "
            f"Provider {self.provider_user_id} @ {self.start_datetime}>"
        )
