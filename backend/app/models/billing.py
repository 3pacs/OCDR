"""Billing records model — core table for all patient billing data."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class BillingRecord(Base):
    __tablename__ = "billing_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    referring_doctor: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    scan_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    gado_used: Mapped[bool] = mapped_column(Boolean, default=False)
    insurance_carrier: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    modality: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    service_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    primary_payment: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    secondary_payment: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    total_payment: Mapped[float] = mapped_column(Numeric(10, 2), default=0, index=True)
    extra_charges: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    reading_physician: Mapped[str | None] = mapped_column(String(200), nullable=True)
    patient_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    patient_name_display: Mapped[str | None] = mapped_column(String(200), nullable=True)
    schedule_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    modality_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_month: Mapped[str | None] = mapped_column(String(3), nullable=True)
    service_year: Mapped[str | None] = mapped_column(String(4), nullable=True)
    is_new_patient: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Derived / system fields
    is_psma: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    denial_status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    denial_reason_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    era_claim_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    appeal_deadline: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    import_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    import_file_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_billing_dedup", "patient_name", "service_date", "scan_type", "modality"),
    )
