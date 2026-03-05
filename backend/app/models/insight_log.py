"""Insight log model — structured logs for AI-assisted session continuity."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class InsightLog(Base):
    """Persistent log of system-generated insights and recommendations.

    Designed to be read back by future AI conversations to provide
    continuity, track what was acted on, and measure outcomes.
    """
    __tablename__ = "insight_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Classification
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # DENIAL_PATTERN, UNDERPAYMENT, SECONDARY_MISSING, PAYER_TREND,
    # PHYSICIAN_ALERT, FILING_RISK, REVENUE_OPPORTUNITY, PROCESS_IMPROVEMENT

    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # CRITICAL, HIGH, MEDIUM, LOW, INFO

    # Content
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)

    # Quantification
    estimated_impact: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    affected_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Context for future sessions
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # PAYER, PHYSICIAN, MODALITY, PATIENT, DENIAL_CODE
    entity_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)

    # Structured data for programmatic access
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    # OPEN, ACKNOWLEDGED, IN_PROGRESS, RESOLVED, DISMISSED
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
