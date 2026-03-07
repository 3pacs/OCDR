"""Physician and statement models."""

from sqlalchemy import Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class Physician(Base):
    __tablename__ = "physicians"

    name: Mapped[str] = mapped_column(String(200), primary_key=True)
    physician_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    specialty: Mapped[str | None] = mapped_column(String(100), nullable=True)
    clinic_affiliation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    volume_alert_threshold: Mapped[float] = mapped_column(Numeric(3, 2), default=0.30)


class PhysicianStatement(Base):
    __tablename__ = "physician_statements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    physician_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    statement_period: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)
    total_owed: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    total_paid: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
