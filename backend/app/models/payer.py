"""Payer and fee schedule models."""

from sqlalchemy import Boolean, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class Payer(Base):
    __tablename__ = "payers"

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    filing_deadline_days: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_has_secondary: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_threshold_pct: Mapped[float] = mapped_column(Numeric(3, 2), default=0.25)


class FeeSchedule(Base):
    __tablename__ = "fee_schedule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payer_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    modality: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    expected_rate: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    underpayment_threshold: Mapped[float] = mapped_column(Numeric(3, 2), default=0.80)
