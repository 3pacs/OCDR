from datetime import datetime, timezone
from app.extensions import db


class Claim(db.Model):
    """Insurance claim record (from OfficeAlly or similar)."""
    __tablename__ = "claims"

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(60))          # officeally, candalis, manual
    external_id = db.Column(db.String(100))    # claim ID in source system
    patient_name = db.Column(db.String(200))
    patient_id = db.Column(db.String(100))
    provider_name = db.Column(db.String(200))
    payer_name = db.Column(db.String(200))
    payer_id = db.Column(db.String(60))
    service_date = db.Column(db.Date)
    submitted_date = db.Column(db.Date)
    billed_amount = db.Column(db.Numeric(10, 2), default=0)
    allowed_amount = db.Column(db.Numeric(10, 2), default=0)
    paid_amount = db.Column(db.Numeric(10, 2), default=0)
    adjustment_amount = db.Column(db.Numeric(10, 2), default=0)
    patient_responsibility = db.Column(db.Numeric(10, 2), default=0)
    status = db.Column(db.String(50))          # submitted, pending, paid, denied, adjusted
    denial_reason = db.Column(db.Text)
    raw_data = db.Column(db.Text)              # JSON of original row
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    payments = db.relationship("Payment", back_populates="claim", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "external_id": self.external_id,
            "patient_name": self.patient_name,
            "payer_name": self.payer_name,
            "service_date": self.service_date.isoformat() if self.service_date else None,
            "submitted_date": self.submitted_date.isoformat() if self.submitted_date else None,
            "billed_amount": float(self.billed_amount or 0),
            "allowed_amount": float(self.allowed_amount or 0),
            "paid_amount": float(self.paid_amount or 0),
            "patient_responsibility": float(self.patient_responsibility or 0),
            "status": self.status,
            "denial_reason": self.denial_reason,
        }


class Payment(db.Model):
    """Incoming payment/remittance record (EOB, check, EFT)."""
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(60))          # optumpay, changehealth, officeally, manual
    claim_id = db.Column(db.Integer, db.ForeignKey("claims.id"), nullable=True)
    external_id = db.Column(db.String(100))    # check/EFT number from source
    check_number = db.Column(db.String(100))
    eft_trace_number = db.Column(db.String(100))
    payer_name = db.Column(db.String(200))
    payer_id = db.Column(db.String(60))
    payment_date = db.Column(db.Date)
    payment_type = db.Column(db.String(30))    # check, eft, virtual_card
    amount = db.Column(db.Numeric(10, 2), default=0)
    memo = db.Column(db.String(500))
    status = db.Column(db.String(30), default="unreconciled")  # unreconciled, reconciled, voided
    raw_data = db.Column(db.Text)              # JSON of original EOB row
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    claim = db.relationship("Claim", back_populates="payments")
    reconciliation_match = db.relationship("ReconciliationMatch",
                                           back_populates="payment",
                                           uselist=False)

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "claim_id": self.claim_id,
            "check_number": self.check_number,
            "eft_trace_number": self.eft_trace_number,
            "payer_name": self.payer_name,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "payment_type": self.payment_type,
            "amount": float(self.amount or 0),
            "memo": self.memo,
            "status": self.status,
        }
