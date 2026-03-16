"""Billing records model — core table for all patient billing data.

DATA CLASSIFICATION:
  STATIC fields (from source, should not change after import):
    patient_name, referring_doctor, scan_type, gado_used, insurance_carrier,
    modality, service_date, patient_id, birth_date, modality_code, description,
    service_month, service_year, is_new_patient, topaz_id, is_psma, import_source

  DYNAMIC fields (change through workflow/matching):
    primary_payment, secondary_payment, total_payment, extra_charges,
    denial_status, denial_reason_code, era_claim_id, appeal_deadline

  DERIVED fields (computed by system):
    is_psma (from description), appeal_deadline (from payer filing deadlines)

  EXTERNALLY VALIDATABLE:
    modality: must be in VALID_MODALITIES
    insurance_carrier: should match payers table
    service_date: not future, not before 2010
    payments: non-negative, total ~= primary + secondary
    denial_status: must be in VALID_DENIAL_STATUSES
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Integer,
    Numeric, String, Text, Index, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class BillingRecord(Base):
    __tablename__ = "billing_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # --- STATIC: Source data (locked after import) ---
    patient_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    referring_doctor: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    scan_type: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    gado_used: Mapped[bool] = mapped_column(Boolean, default=False)
    insurance_carrier: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    modality: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    service_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # --- DYNAMIC: Payment fields (updated by ERA matching, manual entry) ---
    primary_payment: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    secondary_payment: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    total_payment: Mapped[float] = mapped_column(Numeric(10, 2), default=0, index=True)
    extra_charges: Mapped[float] = mapped_column(Numeric(10, 2), default=0)

    # --- STATIC: Optional source data ---
    reading_physician: Mapped[str | None] = mapped_column(String(200), nullable=True)
    patient_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    patient_name_display: Mapped[str | None] = mapped_column(String(200), nullable=True)
    schedule_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    modality_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_month: Mapped[str | None] = mapped_column(String(20), nullable=True)
    service_year: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_new_patient: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # STATIC: Crosswalk identifiers
    # patient_id = chart_number / Chart ID (from OCMRI.xlsx)
    # topaz_id = Topaz billing system ID (== ERA claim_id in 835 files)
    #   Sources: Topaz ID column in OCMRI, Patient ID column (new layout),
    #            or crosswalk import from Topaz server exports
    topaz_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    # --- DERIVED: Computed by system ---
    is_psma: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # --- DYNAMIC: Workflow state ---
    denial_status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    denial_reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    era_claim_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    appeal_deadline: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    # --- META: Import tracking ---
    import_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    import_file_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        # Dedup index: prevent identical records
        Index("ix_billing_dedup", "patient_name", "service_date", "scan_type", "modality"),
        # Performance indexes for analytics queries
        Index("ix_billing_carrier_modality", "insurance_carrier", "modality"),
        Index("ix_billing_carrier_payment", "insurance_carrier", "total_payment"),
        Index("ix_billing_denial_lookup", "denial_status", "appeal_deadline"),
        Index("ix_billing_doctor_carrier", "referring_doctor", "insurance_carrier"),
        Index("ix_billing_service_year", "service_year", "insurance_carrier"),
        # Constraints: prevent garbage data at the DB level
        # Note: payment fields allow negatives (refunds, adjustments, takebacks)
        CheckConstraint("length(patient_name) >= 2", name="ck_billing_patient_name_len"),
        CheckConstraint("length(insurance_carrier) >= 1", name="ck_billing_carrier_len"),
        CheckConstraint("length(modality) >= 1", name="ck_billing_modality_len"),
        CheckConstraint("service_date >= '2010-01-01'", name="ck_billing_date_min"),
    )
