"""ERA (835) payment and claim line models."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.session import Base


class ERAPayment(Base):
    __tablename__ = "era_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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
    claim_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    claim_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    billed_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    paid_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    patient_name_835: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    service_date_835: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    cpt_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    cas_group_code: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    cas_reason_code: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    cas_adjustment_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    match_confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    matched_billing_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("billing_records.id"), nullable=True, index=True)

    era_payment: Mapped["ERAPayment"] = relationship(back_populates="claim_lines")
