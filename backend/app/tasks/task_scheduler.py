"""Generate task instances from recurring business task templates."""

from datetime import date, timedelta
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.business_task import BusinessTask, TaskInstance


async def generate_due_tasks(db: AsyncSession) -> int:
    """Check all active recurring tasks and create instances for today if not already created."""
    today = date.today()
    weekday = today.weekday()  # 0=Mon..6=Sun
    day_of_month = today.day

    # Get all active task templates
    result = await db.execute(
        select(BusinessTask).where(BusinessTask.is_active == True)
    )
    tasks = result.scalars().all()

    created = 0
    for task in tasks:
        should_create = False

        if task.frequency == "DAILY":
            should_create = True
        elif task.frequency == "WEEKLY":
            should_create = (weekday == (task.schedule_day or 0))
        elif task.frequency == "BIWEEKLY":
            # Every other week — check if ISO week number is even
            iso_week = today.isocalendar()[1]
            should_create = (weekday == (task.schedule_day or 0)) and (iso_week % 2 == 0)
        elif task.frequency == "MONTHLY":
            target_day = task.schedule_day or 1
            # Handle months with fewer days (e.g., schedule_day=31 in Feb → last day)
            import calendar
            last_day = calendar.monthrange(today.year, today.month)[1]
            should_create = (day_of_month == min(target_day, last_day))
        elif task.frequency == "ONE_TIME":
            # One-time tasks are created manually
            continue

        if not should_create:
            continue

        # Check if instance already exists for today
        existing = await db.execute(
            select(TaskInstance).where(
                and_(
                    TaskInstance.task_id == task.id,
                    TaskInstance.due_date == today,
                )
            )
        )
        if existing.scalar_one_or_none():
            continue

        instance = TaskInstance(
            task_id=task.id,
            due_date=today,
            status="PENDING",
        )
        db.add(instance)
        created += 1

    await db.commit()
    return created
