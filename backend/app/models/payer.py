"""Payer and fee schedule models.

DATA CLASSIFICATION:
  SEMI-STATIC: Payer codes, display names, filing deadlines
    - New payers appear ~1-2x per year
    - Filing deadlines change when contracts renegotiate
    - Must be seeded before importing billing data

  SEMI-STATIC: Fee schedule rates
    - Renegotiated annually per contract
    - Payer+modality combos are unique
    - DEFAULT payer_code = fallback when no payer-specific rate

  EXTERNALLY VALIDATABLE:
    - filing_deadline_days: 30-730 range for real payers, 9999 for self-pay
    - expected_rate: positive, reasonable range ($50-$50,000)
    - underpayment_threshold: 0.50-1.00 (50%-100%)
"""

from sqlalchemy import (
    Boolean, CheckConstraint, Integer, Numeric, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class Payer(Base):
    __tablename__ = "payers"

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    filing_deadline_days: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_has_secondary: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_threshold_pct: Mapped[float] = mapped_column(Numeric(3, 2), default=0.25)

    __table_args__ = (
        CheckConstraint("filing_deadline_days > 0", name="ck_payer_deadline_positive"),
        CheckConstraint("alert_threshold_pct >= 0 AND alert_threshold_pct <= 1", name="ck_payer_threshold_range"),
    )


class FeeSchedule(Base):
    __tablename__ = "fee_schedule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payer_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    modality: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # Optional CPT code for procedure-specific rates. NULL = modality-level default.
    # When set, this rate takes priority over the modality-level rate.
    cpt_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    expected_rate: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    underpayment_threshold: Mapped[float] = mapped_column(Numeric(3, 2), default=0.80)

    __table_args__ = (
        # Unique on (payer, modality, cpt) — allows both modality-level and CPT-level rates
        UniqueConstraint("payer_code", "modality", "cpt_code", name="uq_fee_schedule_payer_modality_cpt"),
        CheckConstraint("expected_rate > 0", name="ck_fee_rate_positive"),
        CheckConstraint(
            "underpayment_threshold >= 0.3 AND underpayment_threshold <= 1.0",
            name="ck_fee_threshold_range",
        ),
    )
