from datetime import datetime, timezone
from app import db


class BillingRecord(db.Model):
    __tablename__ = 'billing_records'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    patient_name = db.Column(db.Text, nullable=False, index=True)
    referring_doctor = db.Column(db.Text, nullable=False, index=True)
    scan_type = db.Column(db.Text, nullable=False, index=True)
    gado_used = db.Column(db.Boolean, default=False)
    insurance_carrier = db.Column(db.Text, nullable=False, index=True)
    modality = db.Column(db.Text, nullable=False, index=True)
    service_date = db.Column(db.Date, nullable=False, index=True)
    primary_payment = db.Column(db.Numeric(10, 2), default=0)
    secondary_payment = db.Column(db.Numeric(10, 2), default=0)
    total_payment = db.Column(db.Numeric(10, 2), default=0, index=True)
    extra_charges = db.Column(db.Numeric(10, 2), default=0)
    reading_physician = db.Column(db.Text)
    patient_id = db.Column(db.Integer, index=True)
    birth_date = db.Column(db.Date)
    description = db.Column(db.Text)
    is_psma = db.Column(db.Boolean, default=False, index=True)
    denial_status = db.Column(db.Text, index=True)
    denial_reason_code = db.Column(db.Text, index=True)
    era_claim_id = db.Column(db.Text, index=True)
    appeal_deadline = db.Column(db.Date, index=True)
    import_source = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class EraPayment(db.Model):
    __tablename__ = 'era_payments'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    filename = db.Column(db.Text, nullable=False, index=True)
    check_eft_number = db.Column(db.Text, index=True)
    payer_name = db.Column(db.Text)
    payment_date = db.Column(db.Date)
    total_paid = db.Column(db.Numeric(10, 2), default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class EraClaimLine(db.Model):
    __tablename__ = 'era_claim_lines'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    era_payment_id = db.Column(db.Integer, db.ForeignKey('era_payments.id'), index=True)
    claim_id = db.Column(db.Text, index=True)
    patient_name = db.Column(db.Text)
    service_date = db.Column(db.Date)
    cpt_code = db.Column(db.Text)
    billed_amount = db.Column(db.Numeric(10, 2), default=0)
    paid_amount = db.Column(db.Numeric(10, 2), default=0)
    adjustment_amount = db.Column(db.Numeric(10, 2), default=0)
    adjustment_reason = db.Column(db.Text)
    remark_code = db.Column(db.Text)

    era_payment = db.relationship('EraPayment', backref='claim_lines')


class Payer(db.Model):
    __tablename__ = 'payers'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.Text, nullable=False, unique=True)
    name = db.Column(db.Text, nullable=False)
    filing_limit_days = db.Column(db.Integer, default=365)
    expected_turnaround_days = db.Column(db.Integer, default=30)
    has_secondary = db.Column(db.Boolean, default=False)


class FeeSchedule(db.Model):
    __tablename__ = 'fee_schedule'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    payer_code = db.Column(db.Text, db.ForeignKey('payers.code'), index=True)
    modality = db.Column(db.Text, nullable=False)
    expected_rate = db.Column(db.Numeric(10, 2), nullable=False)

    payer = db.relationship('Payer', backref='fee_schedules')


class Physician(db.Model):
    __tablename__ = 'physicians'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.Text, nullable=False, unique=True)
    role = db.Column(db.Text)  # REFERRING, READING
    specialty = db.Column(db.Text)


class PhysicianStatement(db.Model):
    __tablename__ = 'physician_statements'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    physician_id = db.Column(db.Integer, db.ForeignKey('physicians.id'), index=True)
    month = db.Column(db.Text, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    total_reads = db.Column(db.Integer, default=0)
    total_payment = db.Column(db.Numeric(10, 2), default=0)
    generated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    pdf_path = db.Column(db.Text)

    physician = db.relationship('Physician', backref='statements')


class CalendarConfig(db.Model):
    """Stores the path to the folder containing schedule PDFs."""
    __tablename__ = 'calendar_config'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    pdf_folder_path = db.Column(db.Text, nullable=False)
    set_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class CalendarEntry(db.Model):
    """Individual schedule entries extracted from PDF calendars via OCR or Candelis.

    Each row represents one appointment slot pulled from a scanned schedule page
    or ingested from the Candelis RIS.  Cross-referenced with billing_records via
    accession_number, patient_id/MRN, jacket_number, birth_date, or fuzzy name.
    """
    __tablename__ = 'calendar_entries'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    source_pdf = db.Column(db.Text, index=True)
    page_number = db.Column(db.Integer)
    schedule_date = db.Column(db.Date, index=True)
    time_slot = db.Column(db.Text)
    patient_name = db.Column(db.Text, index=True)
    patient_id = db.Column(db.Integer, index=True)
    jacket_number = db.Column(db.Text, index=True)
    birth_date = db.Column(db.Date)
    scan_type = db.Column(db.Text)
    modality = db.Column(db.Text, index=True)
    referring_doctor = db.Column(db.Text)
    insurance_carrier = db.Column(db.Text)
    notes = db.Column(db.Text)
    raw_ocr_text = db.Column(db.Text)
    billing_record_id = db.Column(db.Integer, db.ForeignKey('billing_records.id'), index=True)
    match_confidence = db.Column(db.Numeric(5, 4))
    match_method = db.Column(db.Text)  # accession, patient_id, jacket_number, dob+name, fuzzy_name
    ocr_processed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # ── Candelis provenance fields ──
    source_system = db.Column(db.Text, index=True)  # PDF_OCR, CANDELIS
    candelis_study_id = db.Column(db.Integer, db.ForeignKey('candelis_studies.id'), index=True)
    accession_number = db.Column(db.Text, index=True)
    mrn = db.Column(db.Text, index=True)  # Medical Record Number
    gender = db.Column(db.Text)
    phone = db.Column(db.Text)
    study_status = db.Column(db.Text, index=True)  # SCHEDULED, COMPLETED, CANCELLED, NO_SHOW
    study_description = db.Column(db.Text)
    reading_physician = db.Column(db.Text)
    location = db.Column(db.Text)
    synced_at = db.Column(db.DateTime)  # When this row was synced from Candelis

    billing_record = db.relationship('BillingRecord', backref='calendar_entries')
    candelis_study = db.relationship('CandelisStudy', backref='calendar_entries')


class CandelisConfig(db.Model):
    """Connection settings for the Candelis RIS database (SQL Server on LAN)."""
    __tablename__ = 'candelis_config'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    server = db.Column(db.Text, nullable=False)
    database = db.Column(db.Text, nullable=False)
    username = db.Column(db.Text, nullable=False)
    password = db.Column(db.Text, nullable=False)
    port = db.Column(db.Integer, default=1433)
    driver = db.Column(db.Text, default='ODBC Driver 17 for SQL Server')
    # Candelis schema mapping — table/column names may vary per site
    study_table = db.Column(db.Text, default='Study')
    patient_table = db.Column(db.Text, default='Patient')
    auto_sync_enabled = db.Column(db.Boolean, default=False)
    sync_interval_minutes = db.Column(db.Integer, default=60)
    last_sync_at = db.Column(db.DateTime)
    last_sync_status = db.Column(db.Text)  # success, error
    last_sync_message = db.Column(db.Text)
    last_sync_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))


class CandelisStudy(db.Model):
    """Raw study/exam record ingested from Candelis RIS.

    Stores the full Candelis record with all identifying fields intact,
    serving as the single source of truth for data lineage.  Mapped into
    CalendarEntry rows for schedule display and billing matching.
    """
    __tablename__ = 'candelis_studies'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # ── Candelis identifiers ──
    candelis_key = db.Column(db.Text, unique=True, index=True)  # PK from Candelis
    accession_number = db.Column(db.Text, index=True)
    # ── Patient identifiers ──
    mrn = db.Column(db.Text, index=True)
    patient_name = db.Column(db.Text, index=True)
    patient_last_name = db.Column(db.Text, index=True)
    patient_first_name = db.Column(db.Text, index=True)
    birth_date = db.Column(db.Date)
    gender = db.Column(db.Text)
    phone = db.Column(db.Text)
    ssn_last4 = db.Column(db.Text)  # Last 4 of SSN if available
    jacket_number = db.Column(db.Text, index=True)
    # ── Study details ──
    study_date = db.Column(db.Date, index=True)
    study_time = db.Column(db.Text)
    modality = db.Column(db.Text, index=True)
    study_description = db.Column(db.Text)
    body_part = db.Column(db.Text)
    # ── Physicians ──
    referring_physician = db.Column(db.Text, index=True)
    reading_physician = db.Column(db.Text)
    # ── Insurance / billing ──
    insurance_carrier = db.Column(db.Text)
    insurance_id = db.Column(db.Text)
    authorization_number = db.Column(db.Text)
    # ── Status & location ──
    study_status = db.Column(db.Text, index=True)  # SCHEDULED, COMPLETED, etc.
    location = db.Column(db.Text)
    # ── Provenance ──
    raw_data = db.Column(db.Text)  # JSON dump of full Candelis row
    ingested_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))


class DevNote(db.Model):
    """Development notes stored via the chatbot interface.

    Notes with status='open' are actionable items for Claude Code to resolve.
    Categories help organize notes by area of concern.
    """
    __tablename__ = 'dev_notes'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.Text, nullable=False, default='general')
    status = db.Column(db.Text, nullable=False, default='open')  # open, in_progress, resolved, wontfix
    priority = db.Column(db.Text, nullable=False, default='normal')  # low, normal, high, critical
    resolution = db.Column(db.Text)  # What was done to resolve it
    file_path = db.Column(db.Text)  # Optional: specific file this note relates to
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))
