from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


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
    import_source = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
            "import_source": self.import_source,
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
    parsed_at = db.Column(db.DateTime, default=datetime.utcnow)

    claim_lines = db.relationship("EraClaimLine", backref="era_payment", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "check_eft_number": self.check_eft_number,
            "payment_amount": self.payment_amount,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "payment_method": self.payment_method,
            "payer_name": self.payer_name,
            "parsed_at": self.parsed_at.isoformat() if self.parsed_at else None,
            "claim_count": len(self.claim_lines) if self.claim_lines else 0,
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
    matched_billing_id = db.Column(db.Integer, index=True)

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
    expected_rate = db.Column(db.Float, nullable=False)
    underpayment_threshold = db.Column(db.Float, default=0.80)


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
    modality = db.Column(db.Text, nullable=False, index=True)  # MRI, CT, PET
    scheduled_date = db.Column(db.Date, nullable=False, index=True)
    scheduled_time = db.Column(db.Text)  # HH:MM format
    referring_doctor = db.Column(db.Text, index=True)
    insurance_carrier = db.Column(db.Text)
    location = db.Column(db.Text)
    status = db.Column(db.Text, default="SCHEDULED", index=True)  # SCHEDULED, COMPLETED, CANCELLED, NO_SHOW
    notes = db.Column(db.Text)
    import_source = db.Column(db.Text)  # FOLDER_IMPORT, MANUAL, SEED_DATA
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    action = db.Column(db.Text, nullable=False)  # CONFIRMED, REJECTED, REASSIGNED
    original_score = db.Column(db.Float)
    name_score = db.Column(db.Float)
    date_score = db.Column(db.Float)
    modality_score = db.Column(db.Float)
    carrier = db.Column(db.Text, index=True)
    modality = db.Column(db.Text, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class NameAlias(db.Model):
    """Stores confirmed patient name pairs (SM-04)."""
    __tablename__ = "name_aliases"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name_a = db.Column(db.Text, nullable=False, index=True)
    name_b = db.Column(db.Text, nullable=False, index=True)
    match_count = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LearnedWeights(db.Model):
    """Stores optimized weights per carrier/modality (SM-01b, SM-02)."""
    __tablename__ = "learned_weights"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    carrier = db.Column(db.Text, index=True)  # NULL = global default
    modality = db.Column(db.Text, index=True)  # NULL = all modalities
    name_weight = db.Column(db.Float, nullable=False, default=0.50)
    date_weight = db.Column(db.Float, nullable=False, default=0.30)
    modality_weight = db.Column(db.Float, nullable=False, default=0.20)
    auto_accept_threshold = db.Column(db.Float, nullable=False, default=0.95)
    review_threshold = db.Column(db.Float, nullable=False, default=0.80)
    sample_size = db.Column(db.Integer, default=0)
    accuracy = db.Column(db.Float)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


class LearnedCptModality(db.Model):
    """Stores CPT->modality mappings learned from confirmed matches (SM-05)."""
    __tablename__ = "learned_cpt_modality"

    cpt_prefix = db.Column(db.Text, primary_key=True)
    modality = db.Column(db.Text, nullable=False)
    confidence = db.Column(db.Float, default=1.0)
    source = db.Column(db.Text, nullable=False, default="HARDCODED")  # HARDCODED or LEARNED
    match_count = db.Column(db.Integer, default=1)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


class DenialOutcome(db.Model):
    """Stores appeal results for learning recovery rates (SM-03)."""
    __tablename__ = "denial_outcomes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    billing_record_id = db.Column(db.Integer, db.ForeignKey("billing_records.id"), nullable=False, index=True)
    carrier = db.Column(db.Text, nullable=False, index=True)
    denial_reason = db.Column(db.Text, index=True)
    modality = db.Column(db.Text, index=True)
    days_old_at_appeal = db.Column(db.Integer)
    outcome = db.Column(db.Text, nullable=False)  # RECOVERED, PARTIAL, WRITTEN_OFF
    recovered_amount = db.Column(db.Float, default=0.0)
    expected_amount = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ColumnAliasLearned(db.Model):
    """Stores import column mappings learned from user corrections (SM-08)."""
    __tablename__ = "column_aliases_learned"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    source_name = db.Column(db.Text, nullable=False, index=True)
    target_field = db.Column(db.Text, nullable=False)
    source_format = db.Column(db.Text)  # CSV, EXCEL, PDF
    confidence = db.Column(db.Float, default=1.0)
    use_count = db.Column(db.Integer, default=1)


class NormalizationLearned(db.Model):
    """Stores new modality/carrier normalizations from user approvals (SM-09)."""
    __tablename__ = "normalization_learned"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    category = db.Column(db.Text, nullable=False, index=True)  # MODALITY or CARRIER
    raw_value = db.Column(db.Text, nullable=False, index=True)
    normalized_value = db.Column(db.Text, nullable=False)
    approved = db.Column(db.Boolean, default=False)
    use_count = db.Column(db.Integer, default=1)
