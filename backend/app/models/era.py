"""ERA (835) payment and claim line models.

DATA CLASSIFICATION:
  STATIC: All fields are immutable after 835 file parsing.
    Payment data comes from payer remittance files — these are the
    payer's authoritative record of what they paid and why.

  DYNAMIC: Only match_confidence and matched_billing_id change
    (updated by the auto-matcher linking ERA lines to billing records).

  EXTERNALLY VALIDATABLE:
    - claim_status: X12 835 claim status codes (1, 2, 4, 22, 23)
    - cas_group_code: ANSI adjustment group (CO, CR, OA, PI, PR)
    - cpt_code: 5-digit CPT code (validate against CMS)
    - payment_method: CHK, ACH, NON, FWT, BOP
    - match_confidence: 0.00 to 1.00
"""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.session import Base


class ERAPayment(Base):
    __tablename__ = "era_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # STATIC: From 835 file header
    filename: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    check_eft_number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    payment_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    payer_name: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    parsed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    claim_lines: Mapped[list["ERAClaimLine"]] = relationship(back_populates="era_payment", cascade="all, delete-orphan")


class ERAClaimLine(Base):
    __tablename__ = "era_claim_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    era_payment_id: Mapped[int] = mapped_column(Integer, ForeignKey("era_payments.id"), nullable=False, index=True)

    # STATIC: From 835 claim segment (CLP)
    claim_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    claim_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    billed_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    paid_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    patient_name_835: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    service_date_835: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    cpt_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    # STATIC: From 835 adjustment segment (CAS)
    cas_group_code: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    cas_reason_code: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    cas_adjustment_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    # STATIC: Diagnosis codes (from 837 claim or Topaz import — NOT in 835)
    # Stored as comma-separated ICD-10 codes (e.g., "C61,Z85.46")
    diagnosis_codes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # DYNAMIC: Updated by auto-matcher
    match_confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    matched_billing_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("billing_records.id"), nullable=True, index=True)

    era_payment: Mapped["ERAPayment"] = relationship(back_populates="claim_lines")

    __table_args__ = (
        # Performance: payer match lookups
        Index("ix_era_claim_match", "patient_name_835", "service_date_835"),
        Index("ix_era_claim_status_group", "claim_status", "cas_group_code"),
        # Constraints
        CheckConstraint(
            "claim_status IS NULL OR claim_status IN "
            "('1','2','3','4','5','10','13','15','16','17','19','20','21','22','23','25')",
            name="ck_era_claim_status",
        ),
        CheckConstraint(
            "cas_group_code IS NULL OR cas_group_code IN ('CO','CR','OA','PI','PR')",
            name="ck_era_cas_group",
        ),
        CheckConstraint(
            "match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1)",
            name="ck_era_confidence_range",
        ),
    )
