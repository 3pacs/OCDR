"""Generate task instances from recurring business task templates."""

import calendar
from datetime import date

from sqlalchemy import and_

from app.models import db, BusinessTask, TaskInstance


def generate_due_tasks() -> int:
    """Check all active recurring tasks and create instances for today if not already created."""
    today = date.today()
    weekday = today.weekday()  # 0=Mon..6=Sun
    day_of_month = today.day

    tasks = BusinessTask.query.filter_by(is_active=True).all()

    created = 0
    for task in tasks:
        should_create = False

        if task.frequency == "DAILY":
            should_create = True
        elif task.frequency == "WEEKLY":
            should_create = (weekday == (task.schedule_day or 0))
        elif task.frequency == "BIWEEKLY":
            iso_week = today.isocalendar()[1]
            should_create = (weekday == (task.schedule_day or 0)) and (iso_week % 2 == 0)
        elif task.frequency == "MONTHLY":
            target_day = task.schedule_day or 1
            last_day = calendar.monthrange(today.year, today.month)[1]
            should_create = (day_of_month == min(target_day, last_day))
        elif task.frequency == "ONE_TIME":
            continue

        if not should_create:
            continue

        # Check if instance already exists for today
        existing = TaskInstance.query.filter(
            and_(
                TaskInstance.task_id == task.id,
                TaskInstance.due_date == today,
            )
        ).first()
        if existing:
            continue

        instance = TaskInstance(
            task_id=task.id,
            due_date=today,
            status="PENDING",
        )
        db.session.add(instance)
        created += 1

    db.session.commit()
    return created
