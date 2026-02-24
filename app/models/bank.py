from datetime import datetime, timezone
from app.extensions import db


class BankStatement(db.Model):
    """An imported bank statement file."""
    __tablename__ = "bank_statements"

    id = db.Column(db.Integer, primary_key=True)
    account_name = db.Column(db.String(200))
    account_number_last4 = db.Column(db.String(4))
    statement_start = db.Column(db.Date)
    statement_end = db.Column(db.Date)
    file_format = db.Column(db.String(20))    # csv, ofx, qfx, manual
    original_filename = db.Column(db.String(255))
    opening_balance = db.Column(db.Numeric(12, 2), default=0)
    closing_balance = db.Column(db.Numeric(12, 2), default=0)
    notes = db.Column(db.Text)
    imported_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    transactions = db.relationship("BankTransaction", back_populates="statement",
                                   lazy="dynamic", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "account_name": self.account_name,
            "account_number_last4": self.account_number_last4,
            "statement_start": self.statement_start.isoformat() if self.statement_start else None,
            "statement_end": self.statement_end.isoformat() if self.statement_end else None,
            "file_format": self.file_format,
            "original_filename": self.original_filename,
            "opening_balance": float(self.opening_balance or 0),
            "closing_balance": float(self.closing_balance or 0),
            "imported_at": self.imported_at.isoformat() if self.imported_at else None,
        }


class BankTransaction(db.Model):
    """A single transaction line from a bank statement."""
    __tablename__ = "bank_transactions"

    id = db.Column(db.Integer, primary_key=True)
    statement_id = db.Column(db.Integer, db.ForeignKey("bank_statements.id"), nullable=False)
    transaction_date = db.Column(db.Date, nullable=False)
    post_date = db.Column(db.Date)
    description = db.Column(db.String(500))
    amount = db.Column(db.Numeric(12, 2), nullable=False)  # positive=credit, negative=debit
    transaction_type = db.Column(db.String(30))  # credit, debit, check, eft, fee
    check_number = db.Column(db.String(30))
    reference_number = db.Column(db.String(100))
    balance = db.Column(db.Numeric(12, 2))
    category = db.Column(db.String(100))      # payment_received, vendor_payment, fee, etc.
    notes = db.Column(db.Text)
    reconciliation_status = db.Column(db.String(20), default="unmatched")
    # unmatched, matched, manual_match, ignored

    statement = db.relationship("BankStatement", back_populates="transactions")
    reconciliation_match = db.relationship("ReconciliationMatch",
                                           back_populates="bank_transaction",
                                           uselist=False)

    def to_dict(self):
        return {
            "id": self.id,
            "statement_id": self.statement_id,
            "transaction_date": self.transaction_date.isoformat() if self.transaction_date else None,
            "description": self.description,
            "amount": float(self.amount or 0),
            "transaction_type": self.transaction_type,
            "check_number": self.check_number,
            "reference_number": self.reference_number,
            "balance": float(self.balance) if self.balance is not None else None,
            "category": self.category,
            "notes": self.notes,
            "reconciliation_status": self.reconciliation_status,
        }


class ReconciliationMatch(db.Model):
    """Links a Payment record to a BankTransaction."""
    __tablename__ = "reconciliation_matches"

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=True)
    bank_transaction_id = db.Column(db.Integer, db.ForeignKey("bank_transactions.id"),
                                    nullable=False)
    match_type = db.Column(db.String(20), default="auto")  # auto, manual
    confidence = db.Column(db.Numeric(4, 3), default=1.0)  # 0.0-1.0
    notes = db.Column(db.Text)
    matched_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    matched_by = db.Column(db.String(100), default="system")

    payment = db.relationship("Payment", back_populates="reconciliation_match")
    bank_transaction = db.relationship("BankTransaction",
                                       back_populates="reconciliation_match")

    def to_dict(self):
        return {
            "id": self.id,
            "payment_id": self.payment_id,
            "bank_transaction_id": self.bank_transaction_id,
            "match_type": self.match_type,
            "confidence": float(self.confidence) if self.confidence is not None else None,
            "notes": self.notes,
            "matched_at": self.matched_at.isoformat() if self.matched_at else None,
            "matched_by": self.matched_by,
        }
