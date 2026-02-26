from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


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
    primary_payment = db.Column(db.Float, default=0.0)
    secondary_payment = db.Column(db.Float, default=0.0)
    total_payment = db.Column(db.Float, default=0.0, index=True)
    extra_charges = db.Column(db.Float, default=0.0)
    reading_physician = db.Column(db.Text)
    patient_id = db.Column(db.Integer, index=True)
    birth_date = db.Column(db.Date)
    schedule_date = db.Column(db.Date)
    modality_code = db.Column(db.Text)
    description = db.Column(db.Text)
    is_new_patient = db.Column(db.Boolean, default=False)
    is_psma = db.Column(db.Boolean, default=False, index=True)
    cap_exception = db.Column(db.Boolean, default=False)
    denial_status = db.Column(db.Text, index=True)
    denial_reason_code = db.Column(db.Text, index=True)
    era_claim_id = db.Column(db.Integer, db.ForeignKey('era_claim_lines.id'), index=True)
    appeal_deadline = db.Column(db.Date, index=True)
    import_source = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'patient_name': self.patient_name,
            'referring_doctor': self.referring_doctor,
            'scan_type': self.scan_type,
            'gado_used': self.gado_used,
            'insurance_carrier': self.insurance_carrier,
            'modality': self.modality,
            'service_date': self.service_date.isoformat() if self.service_date else None,
            'primary_payment': self.primary_payment,
            'secondary_payment': self.secondary_payment,
            'total_payment': self.total_payment,
            'extra_charges': self.extra_charges,
            'reading_physician': self.reading_physician,
            'patient_id': self.patient_id,
            'description': self.description,
            'is_psma': self.is_psma,
            'denial_status': self.denial_status,
            'denial_reason_code': self.denial_reason_code,
            'era_claim_id': self.era_claim_id,
            'appeal_deadline': self.appeal_deadline.isoformat() if self.appeal_deadline else None,
            'import_source': self.import_source,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class EraPayment(db.Model):
    __tablename__ = 'era_payments'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    filename = db.Column(db.Text, nullable=False, index=True)
    check_eft_number = db.Column(db.Text, index=True)
    payment_amount = db.Column(db.Float)
    payment_date = db.Column(db.Date)
    payment_method = db.Column(db.Text)
    payer_name = db.Column(db.Text, index=True)
    parsed_at = db.Column(db.DateTime, default=datetime.utcnow)

    claim_lines = db.relationship('EraClaimLine', backref='era_payment', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'check_eft_number': self.check_eft_number,
            'payment_amount': self.payment_amount,
            'payment_date': self.payment_date.isoformat() if self.payment_date else None,
            'payment_method': self.payment_method,
            'payer_name': self.payer_name,
            'parsed_at': self.parsed_at.isoformat() if self.parsed_at else None,
            'claim_count': len(self.claim_lines) if self.claim_lines else 0,
        }


class EraClaimLine(db.Model):
    __tablename__ = 'era_claim_lines'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    era_payment_id = db.Column(db.Integer, db.ForeignKey('era_payments.id'), nullable=False, index=True)
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
    matched_billing_id = db.Column(db.Integer, db.ForeignKey('billing_records.id'), index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'era_payment_id': self.era_payment_id,
            'claim_id': self.claim_id,
            'claim_status': self.claim_status,
            'billed_amount': self.billed_amount,
            'paid_amount': self.paid_amount,
            'patient_name_835': self.patient_name_835,
            'service_date_835': self.service_date_835.isoformat() if self.service_date_835 else None,
            'cpt_code': self.cpt_code,
            'cas_group_code': self.cas_group_code,
            'cas_reason_code': self.cas_reason_code,
            'cas_adjustment_amount': self.cas_adjustment_amount,
            'match_confidence': self.match_confidence,
            'matched_billing_id': self.matched_billing_id,
        }


class DenialReasonCode(db.Model):
    __tablename__ = 'denial_reason_codes'

    group_code = db.Column(db.Text, primary_key=True)
    reason_code = db.Column(db.Text, primary_key=True)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.Text)

    def to_dict(self):
        return {
            'group_code': self.group_code,
            'reason_code': self.reason_code,
            'description': self.description,
            'category': self.category,
        }


class Payer(db.Model):
    __tablename__ = 'payers'

    code = db.Column(db.Text, primary_key=True)
    display_name = db.Column(db.Text)
    filing_deadline_days = db.Column(db.Integer, nullable=False)
    expected_has_secondary = db.Column(db.Boolean, default=False)
    alert_threshold_pct = db.Column(db.Float, default=0.25)

    def to_dict(self):
        return {
            'code': self.code,
            'display_name': self.display_name,
            'filing_deadline_days': self.filing_deadline_days,
            'expected_has_secondary': self.expected_has_secondary,
            'alert_threshold_pct': self.alert_threshold_pct,
        }


class FeeSchedule(db.Model):
    __tablename__ = 'fee_schedule'

    payer_code = db.Column(db.Text, primary_key=True)
    modality = db.Column(db.Text, primary_key=True)
    expected_rate = db.Column(db.Float, nullable=False)
    underpayment_threshold = db.Column(db.Float, default=0.80)

    def to_dict(self):
        return {
            'payer_code': self.payer_code,
            'modality': self.modality,
            'expected_rate': self.expected_rate,
            'underpayment_threshold': self.underpayment_threshold,
        }


class Physician(db.Model):
    __tablename__ = 'physicians'

    name = db.Column(db.Text, primary_key=True)
    physician_type = db.Column(db.Text)
    specialty = db.Column(db.Text)
    clinic_affiliation = db.Column(db.Text)
    volume_alert_threshold = db.Column(db.Float, default=0.30)

    def to_dict(self):
        return {
            'name': self.name,
            'physician_type': self.physician_type,
            'specialty': self.specialty,
            'clinic_affiliation': self.clinic_affiliation,
            'volume_alert_threshold': self.volume_alert_threshold,
        }


class ScheduleEntry(db.Model):
    __tablename__ = 'schedule_entries'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    patient_name = db.Column(db.Text, nullable=False, index=True)
    schedule_date = db.Column(db.Date, index=True)
    appointment_time = db.Column(db.Text)
    modality = db.Column(db.Text, index=True)
    scan_type = db.Column(db.Text)
    source_file = db.Column(db.Text)
    match_status = db.Column(db.Text, default='UNMATCHED', index=True)
    matched_billing_id = db.Column(db.Integer, db.ForeignKey('billing_records.id'), index=True)
    # Editable fields
    status = db.Column(db.Text, default='SCHEDULED', index=True)  # SCHEDULED, COMPLETED, CANCELLED, NO_SHOW
    notes = db.Column(db.Text)
    referring_doctor = db.Column(db.Text)
    insurance_carrier = db.Column(db.Text)
    ocr_source = db.Column(db.Boolean, default=False)  # True if extracted via OCR
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'patient_name': self.patient_name,
            'schedule_date': self.schedule_date.isoformat() if self.schedule_date else None,
            'appointment_time': self.appointment_time,
            'modality': self.modality,
            'scan_type': self.scan_type,
            'source_file': self.source_file,
            'match_status': self.match_status,
            'matched_billing_id': self.matched_billing_id,
            'status': self.status,
            'notes': self.notes,
            'referring_doctor': self.referring_doctor,
            'insurance_carrier': self.insurance_carrier,
            'ocr_source': self.ocr_source,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class PhysicianStatement(db.Model):
    __tablename__ = 'physician_statements'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    physician_name = db.Column(db.Text, db.ForeignKey('physicians.name'), nullable=False, index=True)
    statement_period = db.Column(db.Text, index=True)
    total_owed = db.Column(db.Float)
    total_paid = db.Column(db.Float, default=0.0)
    status = db.Column(db.Text, default='DRAFT', index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'physician_name': self.physician_name,
            'statement_period': self.statement_period,
            'total_owed': self.total_owed,
            'total_paid': self.total_paid,
            'status': self.status,
        }
