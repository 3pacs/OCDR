"""Business task model — recurring operational tasks for practice management.

Supports daily, weekly, bi-weekly, and monthly recurring schedules.
Each recurring template generates task instances that can be checked off.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, Integer, String, Text, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class BusinessTask(Base):
    """A recurring task template (e.g., 'Import patient data' daily)."""
    __tablename__ = "business_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # DAILY, WEEKLY, BIWEEKLY, MONTHLY, ONE_TIME
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # For WEEKLY: 0=Mon..6=Sun. For MONTHLY: 1-28 day of month. For BIWEEKLY: 0=Mon..6=Sun.
    schedule_day: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Priority: 1=highest, 5=lowest
    priority: Mapped[int] = mapped_column(Integer, default=3)
    # Estimated minutes to complete
    estimated_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Optional metadata
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class TaskInstance(Base):
    """A specific occurrence of a task on a given date."""
    __tablename__ = "task_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # PENDING, COMPLETED, SKIPPED
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
