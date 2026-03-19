from datetime import datetime, date, timezone
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

UTC = timezone.utc


def _utcnow():
    return datetime.now(UTC)


# ══════════════════════════════════════════════════════════════════
#  Lookup / Reference Tables (Sprint 11)
# ══════════════════════════════════════════════════════════════════

class Modality(db.Model):
    """Controlled vocabulary for imaging modalities."""
    __tablename__ = "modalities"

    code = db.Column(db.Text, primary_key=True)  # CT, HMRI, PET, BONE, OPEN, DX, GH
    display_name = db.Column(db.Text, nullable=False)
    category = db.Column(db.Text)  # MRI_GROUP, CT_PET_GROUP
    sort_order = db.Column(db.Integer, default=0)


class ScanType(db.Model):
    """Controlled vocabulary for scan types (body parts)."""
    __tablename__ = "scan_types"

    code = db.Column(db.Text, primary_key=True)
    display_name = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, default=0)


class CptCode(db.Model):
    """CPT code reference table."""
    __tablename__ = "cpt_codes"

    code = db.Column(db.Text, primary_key=True)
    description = db.Column(db.Text)
    modality_code = db.Column(db.Text, db.ForeignKey("modalities.code"))
    source = db.Column(db.Text, default="MANUAL")  # MANUAL, LEARNED, CMS


class CasReasonCode(db.Model):
    """CAS reason code reference table."""
    __tablename__ = "cas_reason_codes"

    code = db.Column(db.Text, primary_key=True)
    group_code = db.Column(db.Text, nullable=False)  # CO, PR, OA, PI, CR
    description = db.Column(db.Text)
    category = db.Column(db.Text)  # CODING, AUTHORIZATION, MEDICAL_NECESSITY


# ══════════════════════════════════════════════════════════════════
#  Core Tables
# ══════════════════════════════════════════════════════════════════

class BillingRecord(db.Model):
    __tablename__ = "billing_records"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    patient_name = db.Column(db.Text, nullable=False, index=True)
    referring_doctor = db.Column(db.Text, nullable=False, index=True)
    scan_type = db.Column(db.Text, nullable=False, index=True)
    gado_used = db.Column(db.Boolean, default=False)
    insurance_carrier = db.Column(db.Text, nullable=False, index=True)
    modality = db.Column(db.Text, nullable=False, index=True)
    service_date = db.Column(db.Date, nullable=False, index=True)
    primary_payment = db.Column(db.Float, default=0.0)
    secondary_payment = db.Column(db.Float, default=0.0)
    total_payment = db.Column(db.Float, default=0.0, index=True)
    extra_charges = db.Column(db.Float, default=0.0)
    reading_physician = db.Column(db.Text)
    patient_id = db.Column(db.Integer, index=True)
    description = db.Column(db.Text)
    is_psma = db.Column(db.Boolean, default=False, index=True)
    denial_status = db.Column(db.Text, index=True)
    denial_reason_code = db.Column(db.Text, index=True)
    era_claim_id = db.Column(db.Text, index=True)
    appeal_deadline = db.Column(db.Date, index=True)
    topaz_patient_id = db.Column(db.Text, index=True)  # Legacy Topaz system patient ID
    import_source = db.Column(db.Text)

    # ── CPT & Charge Detail (Sprint 16) ──────────────────────────
    cpt_code = db.Column(db.Text, index=True)              # CPT code(s) from ERA match, e.g. "71260" or "78815, A9552"
    charge_category = db.Column(db.Text, index=True)       # WITH_CONTRAST, WITHOUT_CONTRAST, PSMA, STANDARD
    contrast_type = db.Column(db.Text)                      # GADOLINIUM, IODINE, ORAL, NONE
    billed_amount = db.Column(db.Float, default=0.0)        # what we billed the insurer
    era_paid_amount = db.Column(db.Float)                   # actual amount paid per ERA 835 (flows back from match)
    patient_responsibility = db.Column(db.Float, default=0.0)  # copay + deductible + coinsurance
    payment_method = db.Column(db.Text)                     # CHECK, EFT, CREDIT_CARD, CASH, MIXED
    adjustment_amount = db.Column(db.Float, default=0.0)    # contractual adjustment from ERA
    write_off_amount = db.Column(db.Float, default=0.0)     # written off amount

    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    # Sprint 11: composite indexes for common queries
    __table_args__ = (
        db.Index("idx_billing_carrier_date", "insurance_carrier", "service_date"),
        db.Index("idx_billing_modality_date", "modality", "service_date"),
        db.Index("idx_billing_denial", "denial_status", "insurance_carrier", "service_date"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "patient_name": self.patient_name,
            "referring_doctor": self.referring_doctor,
            "scan_type": self.scan_type,
            "gado_used": self.gado_used,
            "insurance_carrier": self.insurance_carrier,
            "modality": self.modality,
            "service_date": self.service_date.isoformat() if self.service_date else None,
            "primary_payment": self.primary_payment,
            "secondary_payment": self.secondary_payment,
            "total_payment": self.total_payment,
            "extra_charges": self.extra_charges,
            "reading_physician": self.reading_physician,
            "patient_id": self.patient_id,
            "description": self.description,
            "is_psma": self.is_psma,
            "denial_status": self.denial_status,
            "denial_reason_code": self.denial_reason_code,
            "appeal_deadline": self.appeal_deadline.isoformat() if self.appeal_deadline else None,
            "topaz_patient_id": self.topaz_patient_id,
            "import_source": self.import_source,
            "cpt_code": self.cpt_code,
            "charge_category": self.charge_category,
            "contrast_type": self.contrast_type,
            "billed_amount": self.billed_amount,
            "era_paid_amount": self.era_paid_amount,
            "patient_responsibility": self.patient_responsibility,
            "payment_method": self.payment_method,
            "adjustment_amount": self.adjustment_amount,
            "write_off_amount": self.write_off_amount,
        }


class EraPayment(db.Model):
    __tablename__ = "era_payments"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    filename = db.Column(db.Text, nullable=False, index=True)
    check_eft_number = db.Column(db.Text, index=True)
    payment_amount = db.Column(db.Float)
    payment_date = db.Column(db.Date)
    payment_method = db.Column(db.Text)
    payer_name = db.Column(db.Text, index=True)
    parsed_at = db.Column(db.DateTime, default=_utcnow)

    claim_lines = db.relationship("EraClaimLine", backref="era_payment", lazy=True)

    # Pre-populated by batch queries to avoid N+1
    _claim_count = None

    def to_dict(self):
        # Use pre-populated count if available, else fallback to single query
        if self._claim_count is not None:
            claim_count = self._claim_count
        else:
            from sqlalchemy import text
            from sqlalchemy.orm import object_session
            session = object_session(self)
            if session and self.id:
                claim_count = session.execute(
                    text("SELECT COUNT(*) FROM era_claim_lines WHERE era_payment_id = :pid"),
                    {"pid": self.id}
                ).scalar() or 0
            else:
                claim_count = 0

        return {
            "id": self.id,
            "filename": self.filename,
            "check_eft_number": self.check_eft_number,
            "payment_amount": self.payment_amount,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "payment_method": self.payment_method,
            "payer_name": self.payer_name,
            "parsed_at": self.parsed_at.isoformat() if self.parsed_at else None,
            "claim_count": claim_count,
        }


class EraClaimLine(db.Model):
    __tablename__ = "era_claim_lines"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    era_payment_id = db.Column(
        db.Integer, db.ForeignKey("era_payments.id"), nullable=False, index=True
    )
    claim_id = db.Column(db.Text, index=True)
    claim_status = db.Column(db.Text)
    billed_amount = db.Column(db.Float)
    paid_amount = db.Column(db.Float)
    patient_name_835 = db.Column(db.Text, index=True)
    service_date_835 = db.Column(db.Date, index=True)
    cpt_code = db.Column(db.Text, index=True)
    cas_group_code = db.Column(db.Text, index=True)
    cas_reason_code = db.Column(db.Text, index=True)
    cas_adjustment_amount = db.Column(db.Float)
    match_confidence = db.Column(db.Float)
    matched_billing_id = db.Column(db.Integer, db.ForeignKey("billing_records.id"), index=True)

    # Sprint 11: composite index for matching queries
    __table_args__ = (
        db.Index("idx_era_claims_payment", "era_payment_id", "paid_amount"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "era_payment_id": self.era_payment_id,
            "claim_id": self.claim_id,
            "claim_status": self.claim_status,
            "billed_amount": self.billed_amount,
            "paid_amount": self.paid_amount,
            "patient_name_835": self.patient_name_835,
            "service_date_835": self.service_date_835.isoformat() if self.service_date_835 else None,
            "cpt_code": self.cpt_code,
            "cas_group_code": self.cas_group_code,
            "cas_reason_code": self.cas_reason_code,
            "cas_adjustment_amount": self.cas_adjustment_amount,
            "match_confidence": self.match_confidence,
            "matched_billing_id": self.matched_billing_id,
        }


# ── Junction Tables (Sprint 11) ─────────────────────────────────

class EraClaimCptCode(db.Model):
    """Many-to-many: ERA claim line to CPT codes."""
    __tablename__ = "era_claim_cpt_codes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    era_claim_id = db.Column(db.Integer, db.ForeignKey("era_claim_lines.id"), nullable=False, index=True)
    cpt_code = db.Column(db.Text, nullable=False, index=True)
    billed_amount = db.Column(db.Float)
    paid_amount = db.Column(db.Float)
    units = db.Column(db.Integer, default=1)


class EraClaimAdjustment(db.Model):
    """Many-to-many: ERA claim line to CAS adjustments."""
    __tablename__ = "era_claim_adjustments"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    era_claim_id = db.Column(db.Integer, db.ForeignKey("era_claim_lines.id"), nullable=False, index=True)
    group_code = db.Column(db.Text, nullable=False)
    reason_code = db.Column(db.Text, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, default=0)


# ══════════════════════════════════════════════════════════════════
#  Configuration Tables
# ══════════════════════════════════════════════════════════════════

class Payer(db.Model):
    __tablename__ = "payers"

    code = db.Column(db.Text, primary_key=True)
    display_name = db.Column(db.Text)
    filing_deadline_days = db.Column(db.Integer, nullable=False)
    expected_has_secondary = db.Column(db.Boolean, default=False)
    alert_threshold_pct = db.Column(db.Float, default=0.25)


class FeeSchedule(db.Model):
    __tablename__ = "fee_schedule"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    payer_code = db.Column(db.Text, index=True)
    modality = db.Column(db.Text, index=True)
    cpt_code = db.Column(db.Text, index=True)             # CPT code for CPT-level rates (null = modality-level)
    expected_rate = db.Column(db.Float, nullable=False)
    underpayment_threshold = db.Column(db.Float, default=0.80)
    gado_premium = db.Column(db.Float, default=0.0)
    effective_date = db.Column(db.Date)
    source = db.Column(db.Text, default="MANUAL")
    charge_category = db.Column(db.Text, default="STANDARD")  # STANDARD, WITH_CONTRAST, WITHOUT_CONTRAST, PSMA
    sample_count = db.Column(db.Integer, default=0)        # how many claims this rate was derived from

    __table_args__ = (
        db.UniqueConstraint("payer_code", "modality", name="uq_fee_payer_modality"),
        db.Index("idx_fee_cpt_payer", "cpt_code", "payer_code"),
    )


class Physician(db.Model):
    __tablename__ = "physicians"

    name = db.Column(db.Text, primary_key=True)
    physician_type = db.Column(db.Text)
    specialty = db.Column(db.Text)
    clinic_affiliation = db.Column(db.Text)
    volume_alert_threshold = db.Column(db.Float, default=0.30)


class PhysicianStatement(db.Model):
    __tablename__ = "physician_statements"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    physician_name = db.Column(db.Text, nullable=False, index=True)
    statement_period = db.Column(db.Text, index=True)
    total_owed = db.Column(db.Float)
    total_paid = db.Column(db.Float, default=0.0)
    status = db.Column(db.Text, default="DRAFT", index=True)


class ScheduleRecord(db.Model):
    __tablename__ = "schedule_records"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    patient_name = db.Column(db.Text, nullable=False, index=True)
    scan_type = db.Column(db.Text, nullable=False, index=True)
    modality = db.Column(db.Text, nullable=False, index=True)
    scheduled_date = db.Column(db.Date, nullable=False, index=True)
    scheduled_time = db.Column(db.Text)
    referring_doctor = db.Column(db.Text, index=True)
    insurance_carrier = db.Column(db.Text)
    location = db.Column(db.Text)
    status = db.Column(db.Text, default="SCHEDULED", index=True)
    notes = db.Column(db.Text)
    import_source = db.Column(db.Text)
    source_file = db.Column(db.Text)
    ocr_source = db.Column(db.Boolean, default=False)
    matched_billing_id = db.Column(db.Integer, db.ForeignKey("billing_records.id"), nullable=True)
    match_status = db.Column(db.Text, default="UNMATCHED")
    created_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.Index("idx_schedule_upcoming", "scheduled_date", "status"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "patient_name": self.patient_name,
            "scan_type": self.scan_type,
            "modality": self.modality,
            "scheduled_date": self.scheduled_date.isoformat() if self.scheduled_date else None,
            "scheduled_time": self.scheduled_time,
            "referring_doctor": self.referring_doctor,
            "insurance_carrier": self.insurance_carrier,
            "location": self.location,
            "status": self.status,
            "notes": self.notes,
            "import_source": self.import_source,
            "source_file": self.source_file,
            "ocr_source": self.ocr_source,
            "matched_billing_id": self.matched_billing_id,
            "match_status": self.match_status,
        }


# ══════════════════════════════════════════════════════════════════
#  Payment Detail Tracking (Sprint 16)
# ══════════════════════════════════════════════════════════════════

class PaymentDetail(db.Model):
    """Individual payment transactions against a billing record.

    Tracks each payment event separately (primary EOB, secondary EOB,
    patient payment, etc.) with method and source info.
    """
    __tablename__ = "payment_details"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    billing_record_id = db.Column(db.Integer, db.ForeignKey("billing_records.id"), nullable=False, index=True)
    era_claim_line_id = db.Column(db.Integer, db.ForeignKey("era_claim_lines.id"), index=True)

    payment_type = db.Column(db.Text, nullable=False, index=True)  # PRIMARY, SECONDARY, PATIENT, ADJUSTMENT, WRITE_OFF
    payment_method = db.Column(db.Text, index=True)                # CHECK, EFT, CREDIT_CARD, CASH, ACH, WIRE
    payment_amount = db.Column(db.Float, nullable=False)
    check_number = db.Column(db.Text)
    payer_name = db.Column(db.Text)
    payment_date = db.Column(db.Date, index=True)
    posted_date = db.Column(db.Date)
    source = db.Column(db.Text)                                    # ERA_835, MANUAL, BANK_STATEMENT, LEGACY
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.Index("idx_payment_detail_billing_type", "billing_record_id", "payment_type"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "billing_record_id": self.billing_record_id,
            "era_claim_line_id": self.era_claim_line_id,
            "payment_type": self.payment_type,
            "payment_method": self.payment_method,
            "payment_amount": self.payment_amount,
            "check_number": self.check_number,
            "payer_name": self.payer_name,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "posted_date": self.posted_date.isoformat() if self.posted_date else None,
            "source": self.source,
            "notes": self.notes,
        }


# ══════════════════════════════════════════════════════════════════
#  Smart Matching Models (SM-01 through SM-12)
# ══════════════════════════════════════════════════════════════════

class MatchOutcome(db.Model):
    """Stores every confirm/reject decision for learning (SM-01a)."""
    __tablename__ = "match_outcomes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    era_claim_id = db.Column(db.Integer, db.ForeignKey("era_claim_lines.id"), nullable=False, index=True)
    billing_record_id = db.Column(db.Integer, db.ForeignKey("billing_records.id"), index=True)
    action = db.Column(db.Text, nullable=False)
    original_score = db.Column(db.Float)
    name_score = db.Column(db.Float)
    date_score = db.Column(db.Float)
    modality_score = db.Column(db.Float)
    carrier = db.Column(db.Text, index=True)
    modality = db.Column(db.Text, index=True)
    created_at = db.Column(db.DateTime, default=_utcnow)


class NameAlias(db.Model):
    """Stores confirmed patient name pairs (SM-04)."""
    __tablename__ = "name_aliases"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name_a = db.Column(db.Text, nullable=False, index=True)
    name_b = db.Column(db.Text, nullable=False, index=True)
    match_count = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=_utcnow)


class LearnedWeights(db.Model):
    """Stores optimized weights per carrier/modality (SM-01b, SM-02)."""
    __tablename__ = "learned_weights"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    carrier = db.Column(db.Text, index=True)
    modality = db.Column(db.Text, index=True)
    name_weight = db.Column(db.Float, nullable=False, default=0.50)
    date_weight = db.Column(db.Float, nullable=False, default=0.30)
    modality_weight = db.Column(db.Float, nullable=False, default=0.20)
    auto_accept_threshold = db.Column(db.Float, nullable=False, default=0.95)
    review_threshold = db.Column(db.Float, nullable=False, default=0.80)
    sample_size = db.Column(db.Integer, default=0)
    accuracy = db.Column(db.Float)
    updated_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint("carrier", "modality", name="uq_weights_carrier_modality"),
    )


class LearnedCptModality(db.Model):
    """Stores CPT->modality mappings learned from confirmed matches (SM-05)."""
    __tablename__ = "learned_cpt_modality"

    cpt_prefix = db.Column(db.Text, primary_key=True)
    modality = db.Column(db.Text, nullable=False)
    confidence = db.Column(db.Float, default=1.0)
    source = db.Column(db.Text, nullable=False, default="HARDCODED")
    match_count = db.Column(db.Integer, default=1)
    updated_at = db.Column(db.DateTime, default=_utcnow)


class DenialOutcome(db.Model):
    """Stores appeal results for learning recovery rates (SM-03)."""
    __tablename__ = "denial_outcomes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    billing_record_id = db.Column(db.Integer, db.ForeignKey("billing_records.id"), nullable=False, index=True)
    carrier = db.Column(db.Text, nullable=False, index=True)
    denial_reason = db.Column(db.Text, index=True)
    modality = db.Column(db.Text, index=True)
    days_old_at_appeal = db.Column(db.Integer)
    outcome = db.Column(db.Text, nullable=False)
    recovered_amount = db.Column(db.Float, default=0.0)
    expected_amount = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=_utcnow)


class ColumnAliasLearned(db.Model):
    """Stores import column mappings learned from user corrections (SM-08)."""
    __tablename__ = "column_aliases_learned"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    source_name = db.Column(db.Text, nullable=False, index=True)
    target_field = db.Column(db.Text, nullable=False)
    source_format = db.Column(db.Text)
    confidence = db.Column(db.Float, default=1.0)
    use_count = db.Column(db.Integer, default=1)


class NormalizationLearned(db.Model):
    """Stores new modality/carrier normalizations from user approvals (SM-09)."""
    __tablename__ = "normalization_learned"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    category = db.Column(db.Text, nullable=False, index=True)
    raw_value = db.Column(db.Text, nullable=False, index=True)
    normalized_value = db.Column(db.Text, nullable=False)
    approved = db.Column(db.Boolean, default=False)
    use_count = db.Column(db.Integer, default=1)


# ══════════════════════════════════════════════════════════════════
#  Auth & User Model (Sprint 15)
# ══════════════════════════════════════════════════════════════════

class User(db.Model):
    """Local user accounts for authentication."""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.Text, unique=True, nullable=False, index=True)
    password_hash = db.Column(db.Text, nullable=False)
    role = db.Column(db.Text, nullable=False, default="viewer")  # admin, viewer
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    last_login = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_authenticated(self):
        return True

    def get_id(self):
        return str(self.id)


# ══════════════════════════════════════════════════════════════════
#  Claim Lifecycle (Sprint 14)
# ══════════════════════════════════════════════════════════════════

class ServerFileIndex(db.Model):
    """Tracks files discovered on the records server (X: drive) for read-only extraction."""
    __tablename__ = "server_file_index"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    file_path = db.Column(db.Text, nullable=False, index=True)          # full path on server
    relative_path = db.Column(db.Text, nullable=False, index=True)      # path relative to root
    filename = db.Column(db.Text, nullable=False, index=True)
    extension = db.Column(db.Text, index=True)                          # .835, .csv, .xlsx, etc.
    file_size = db.Column(db.Integer)                                    # bytes
    file_modified = db.Column(db.DateTime)                               # mtime from OS
    detected_format = db.Column(db.Text, index=True)                    # 835, csv, xlsx, pdf, image, etc.
    detected_category = db.Column(db.Text, index=True)                  # billing, era, schedule, pacs, unknown
    detection_confidence = db.Column(db.Float)
    import_status = db.Column(db.Text, default="DISCOVERED", index=True)  # DISCOVERED, IMPORTED, SKIPPED, ERROR
    import_result = db.Column(db.Text)                                   # summary or error message
    records_imported = db.Column(db.Integer, default=0)
    last_scanned = db.Column(db.DateTime, default=_utcnow)
    imported_at = db.Column(db.DateTime)

    __table_args__ = (
        db.Index("idx_server_file_path_mod", "file_path", "file_modified"),
        db.UniqueConstraint("file_path", name="uq_server_file_path"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "file_path": self.file_path,
            "relative_path": self.relative_path,
            "filename": self.filename,
            "extension": self.extension,
            "file_size": self.file_size,
            "file_modified": self.file_modified.isoformat() if self.file_modified else None,
            "detected_format": self.detected_format,
            "detected_category": self.detected_category,
            "detection_confidence": self.detection_confidence,
            "import_status": self.import_status,
            "import_result": self.import_result,
            "records_imported": self.records_imported,
            "last_scanned": self.last_scanned.isoformat() if self.last_scanned else None,
            "imported_at": self.imported_at.isoformat() if self.imported_at else None,
        }


class ClaimStatusHistory(db.Model):
    """Tracks claim state transitions with timestamps."""
    __tablename__ = "claim_status_history"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    billing_record_id = db.Column(db.Integer, db.ForeignKey("billing_records.id"), nullable=False, index=True)
    old_status = db.Column(db.Text)
    new_status = db.Column(db.Text, nullable=False)
    changed_by = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)


# ══════════════════════════════════════════════════════════════════
#  OCR Correction Learning (handwritten schedule import)
# ══════════════════════════════════════════════════════════════════

class OcrCorrection(db.Model):
    """Stores learned OCR corrections for handwritten schedule imports.

    When OCR misreads handwritten text, user corrections are stored here
    and automatically applied to future imports.
    """
    __tablename__ = "ocr_corrections"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ocr_text = db.Column(db.Text, nullable=False, index=True)        # what OCR produced
    corrected_text = db.Column(db.Text, nullable=False)               # what user corrected it to
    field_type = db.Column(db.Text, nullable=False, index=True)       # patient_name, scan_type, modality, doctor, carrier
    correction_count = db.Column(db.Integer, default=1)               # times this correction was applied
    source_file = db.Column(db.Text)                                   # file where first seen
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        db.UniqueConstraint("ocr_text", "field_type", name="uq_ocr_correction"),
    )
