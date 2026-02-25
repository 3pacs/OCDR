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
