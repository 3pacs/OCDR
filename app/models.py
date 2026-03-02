"""SQLAlchemy models for OCDR web application.

Six tables matching the BUILD_SPEC database schema.
"""

from datetime import date, datetime
from decimal import Decimal

from app.extensions import db


class BillingRecord(db.Model):
    __tablename__ = 'billing_records'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    patient_name = db.Column(db.Text, nullable=False, index=True)
    referring_doctor = db.Column(db.Text, nullable=False, default='')
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
    patient_name_display = db.Column(db.Text)
    schedule_date = db.Column(db.Date)
    description = db.Column(db.Text)
    is_psma = db.Column(db.Boolean, default=False, index=True)
    is_new_patient = db.Column(db.Boolean, default=False)
    is_research = db.Column(db.Boolean, default=False)
    denial_status = db.Column(db.Text, index=True)
    denial_reason_code = db.Column(db.Text, index=True)
    era_claim_id = db.Column(db.Text, index=True)
    appeal_deadline = db.Column(db.Date, index=True)
    import_source = db.Column(db.Text)
    source = db.Column(db.Text)
    notes = db.Column(db.Text)
    service_month = db.Column(db.Text)
    service_year = db.Column(db.Text)
    expected_rate = db.Column(db.Numeric(10, 2))
    variance = db.Column(db.Numeric(10, 2))
    pct_of_expected = db.Column(db.Numeric(5, 4))
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())

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
            'primary_payment': float(self.primary_payment) if self.primary_payment else 0,
            'secondary_payment': float(self.secondary_payment) if self.secondary_payment else 0,
            'total_payment': float(self.total_payment) if self.total_payment else 0,
            'extra_charges': float(self.extra_charges) if self.extra_charges else 0,
            'reading_physician': self.reading_physician,
            'patient_id': self.patient_id,
            'birth_date': self.birth_date.isoformat() if self.birth_date else None,
            'patient_name_display': self.patient_name_display,
            'schedule_date': self.schedule_date.isoformat() if self.schedule_date else None,
            'description': self.description,
            'is_psma': self.is_psma,
            'is_new_patient': self.is_new_patient,
            'is_research': self.is_research,
            'denial_status': self.denial_status,
            'denial_reason_code': self.denial_reason_code,
            'era_claim_id': self.era_claim_id,
            'appeal_deadline': self.appeal_deadline.isoformat() if self.appeal_deadline else None,
            'import_source': self.import_source,
            'source': self.source,
            'notes': self.notes,
            'service_month': self.service_month,
            'service_year': self.service_year,
            'expected_rate': float(self.expected_rate) if self.expected_rate else None,
            'variance': float(self.variance) if self.variance else None,
            'pct_of_expected': float(self.pct_of_expected) if self.pct_of_expected else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class EraPayment(db.Model):
    __tablename__ = 'era_payments'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    filename = db.Column(db.Text, nullable=False, index=True)
    check_eft_number = db.Column(db.Text, index=True)
    payment_amount = db.Column(db.Numeric(10, 2))
    payment_date = db.Column(db.Date)
    payment_method = db.Column(db.Text)
    payer_name = db.Column(db.Text, index=True)
    parsed_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    claim_lines = db.relationship('EraClaimLine', backref='era_payment', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'check_eft_number': self.check_eft_number,
            'payment_amount': float(self.payment_amount) if self.payment_amount else 0,
            'payment_date': self.payment_date.isoformat() if self.payment_date else None,
            'payment_method': self.payment_method,
            'payer_name': self.payer_name,
            'parsed_at': self.parsed_at.isoformat() if self.parsed_at else None,
        }


class EraClaimLine(db.Model):
    __tablename__ = 'era_claim_lines'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    era_payment_id = db.Column(db.Integer, db.ForeignKey('era_payments.id'), nullable=False, index=True)
    claim_id = db.Column(db.Text, index=True)
    claim_status = db.Column(db.Text)
    billed_amount = db.Column(db.Numeric(10, 2))
    paid_amount = db.Column(db.Numeric(10, 2))
    patient_name_835 = db.Column(db.Text, index=True)
    service_date_835 = db.Column(db.Date, index=True)
    cpt_code = db.Column(db.Text, index=True)
    cas_group_code = db.Column(db.Text, index=True)
    cas_reason_code = db.Column(db.Text, index=True)
    cas_adjustment_amount = db.Column(db.Numeric(10, 2))
    match_confidence = db.Column(db.Numeric(3, 2))
    matched_billing_id = db.Column(db.Integer, db.ForeignKey('billing_records.id'), index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'era_payment_id': self.era_payment_id,
            'claim_id': self.claim_id,
            'claim_status': self.claim_status,
            'billed_amount': float(self.billed_amount) if self.billed_amount else 0,
            'paid_amount': float(self.paid_amount) if self.paid_amount else 0,
            'patient_name_835': self.patient_name_835,
            'service_date_835': self.service_date_835.isoformat() if self.service_date_835 else None,
            'cpt_code': self.cpt_code,
            'cas_group_code': self.cas_group_code,
            'cas_reason_code': self.cas_reason_code,
            'cas_adjustment_amount': float(self.cas_adjustment_amount) if self.cas_adjustment_amount else 0,
            'match_confidence': float(self.match_confidence) if self.match_confidence else None,
            'matched_billing_id': self.matched_billing_id,
        }


class Payer(db.Model):
    __tablename__ = 'payers'

    code = db.Column(db.Text, primary_key=True)
    display_name = db.Column(db.Text)
    filing_deadline_days = db.Column(db.Integer, nullable=False)
    expected_has_secondary = db.Column(db.Boolean, default=False)
    alert_threshold_pct = db.Column(db.Numeric(3, 2), default=0.25)

    def to_dict(self):
        return {
            'code': self.code,
            'display_name': self.display_name,
            'filing_deadline_days': self.filing_deadline_days,
            'expected_has_secondary': self.expected_has_secondary,
            'alert_threshold_pct': float(self.alert_threshold_pct) if self.alert_threshold_pct else 0.25,
        }


class FeeSchedule(db.Model):
    __tablename__ = 'fee_schedule'

    payer_code = db.Column(db.Text, primary_key=True)
    modality = db.Column(db.Text, primary_key=True)
    expected_rate = db.Column(db.Numeric(10, 2), nullable=False)
    underpayment_threshold = db.Column(db.Numeric(3, 2), default=0.80)

    def to_dict(self):
        return {
            'payer_code': self.payer_code,
            'modality': self.modality,
            'expected_rate': float(self.expected_rate) if self.expected_rate else 0,
            'underpayment_threshold': float(self.underpayment_threshold) if self.underpayment_threshold else 0.80,
        }


class Physician(db.Model):
    __tablename__ = 'physicians'

    name = db.Column(db.Text, primary_key=True)
    physician_type = db.Column(db.Text)
    specialty = db.Column(db.Text)
    clinic_affiliation = db.Column(db.Text)
    volume_alert_threshold = db.Column(db.Numeric(3, 2), default=0.30)

    def to_dict(self):
        return {
            'name': self.name,
            'physician_type': self.physician_type,
            'specialty': self.specialty,
            'clinic_affiliation': self.clinic_affiliation,
            'volume_alert_threshold': float(self.volume_alert_threshold) if self.volume_alert_threshold else 0.30,
        }
