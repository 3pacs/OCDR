"""API routes for business task management."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, and_, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db
from backend.app.models.business_task import BusinessTask, TaskInstance
from backend.app.tasks.task_scheduler import generate_due_tasks

router = APIRouter()


# ---------------------------------------------------------------------------
# Task Templates (recurring definitions)
# ---------------------------------------------------------------------------

@router.get("/templates")
async def list_templates(db: AsyncSession = Depends(get_db)):
    """List all business task templates."""
    result = await db.execute(
        select(BusinessTask).order_by(BusinessTask.frequency, BusinessTask.priority)
    )
    tasks = result.scalars().all()
    return [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "category": t.category,
            "frequency": t.frequency,
            "schedule_day": t.schedule_day,
            "priority": t.priority,
            "estimated_minutes": t.estimated_minutes,
            "is_active": t.is_active,
            "notes": t.notes,
        }
        for t in tasks
    ]


class TemplateCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: str
    frequency: str  # DAILY, WEEKLY, BIWEEKLY, MONTHLY, ONE_TIME
    schedule_day: Optional[int] = None
    priority: int = 3
    estimated_minutes: Optional[int] = None
    notes: Optional[str] = None


@router.post("/templates")
async def create_template(body: TemplateCreate, db: AsyncSession = Depends(get_db)):
    """Create a new task template."""
    task = BusinessTask(**body.model_dump())
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return {"id": task.id, "title": task.title, "status": "created"}


class TemplateUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    frequency: Optional[str] = None
    schedule_day: Optional[int] = None
    priority: Optional[int] = None
    estimated_minutes: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


@router.patch("/templates/{task_id}")
async def update_template(task_id: int, body: TemplateUpdate, db: AsyncSession = Depends(get_db)):
    """Update a task template."""
    result = await db.execute(select(BusinessTask).where(BusinessTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task template not found")
    for key, val in body.model_dump(exclude_unset=True).items():
        setattr(task, key, val)
    await db.commit()
    return {"id": task.id, "status": "updated"}


@router.delete("/templates/{task_id}")
async def delete_template(task_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a task template and its instances."""
    result = await db.execute(select(BusinessTask).where(BusinessTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task template not found")
    # Delete instances first
    await db.execute(
        select(TaskInstance).where(TaskInstance.task_id == task_id)
    )
    from sqlalchemy import delete
    await db.execute(delete(TaskInstance).where(TaskInstance.task_id == task_id))
    await db.delete(task)
    await db.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Task Instances (daily checklist)
# ---------------------------------------------------------------------------

@router.get("/today")
async def today_tasks(db: AsyncSession = Depends(get_db)):
    """Get today's task checklist. Auto-generates instances if needed."""
    # Generate any missing instances for today
    await generate_due_tasks(db)

    today = date.today()

    # Get today's instances with their template info
    result = await db.execute(
        select(TaskInstance, BusinessTask)
        .join(BusinessTask, TaskInstance.task_id == BusinessTask.id)
        .where(TaskInstance.due_date == today)
        .order_by(BusinessTask.priority, BusinessTask.title)
    )
    rows = result.all()

    tasks = []
    for instance, template in rows:
        tasks.append({
            "instance_id": instance.id,
            "task_id": template.id,
            "title": template.title,
            "description": template.description,
            "category": template.category,
            "frequency": template.frequency,
            "priority": template.priority,
            "estimated_minutes": template.estimated_minutes,
            "status": instance.status,
            "completed_at": instance.completed_at.isoformat() if instance.completed_at else None,
            "completed_by": instance.completed_by,
            "notes": instance.notes,
        })

    # Summary stats
    total = len(tasks)
    completed = sum(1 for t in tasks if t["status"] == "COMPLETED")
    skipped = sum(1 for t in tasks if t["status"] == "SKIPPED")
    pending = total - completed - skipped
    total_minutes = sum(t["estimated_minutes"] or 0 for t in tasks if t["status"] == "PENDING")

    return {
        "date": today.isoformat(),
        "tasks": tasks,
        "summary": {
            "total": total,
            "completed": completed,
            "skipped": skipped,
            "pending": pending,
            "estimated_minutes_remaining": total_minutes,
        },
    }


@router.get("/history")
async def task_history(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """Get task completion history for the last N days."""
    start_date = date.today() - __import__("datetime").timedelta(days=days)

    result = await db.execute(
        select(TaskInstance, BusinessTask)
        .join(BusinessTask, TaskInstance.task_id == BusinessTask.id)
        .where(TaskInstance.due_date >= start_date)
        .order_by(TaskInstance.due_date.desc(), BusinessTask.priority)
    )
    rows = result.all()

    # Group by date
    by_date = {}
    for instance, template in rows:
        d = instance.due_date.isoformat()
        if d not in by_date:
            by_date[d] = {"date": d, "tasks": [], "completed": 0, "total": 0}
        by_date[d]["tasks"].append({
            "instance_id": instance.id,
            "title": template.title,
            "category": template.category,
            "status": instance.status,
            "completed_at": instance.completed_at.isoformat() if instance.completed_at else None,
        })
        by_date[d]["total"] += 1
        if instance.status == "COMPLETED":
            by_date[d]["completed"] += 1

    return {"days": sorted(by_date.values(), key=lambda x: x["date"], reverse=True)}


class InstanceUpdate(BaseModel):
    status: str  # COMPLETED, SKIPPED, PENDING
    notes: Optional[str] = None
    completed_by: Optional[str] = None


@router.patch("/instances/{instance_id}")
async def update_instance(instance_id: int, body: InstanceUpdate, db: AsyncSession = Depends(get_db)):
    """Update a task instance (complete, skip, or reset)."""
    result = await db.execute(
        select(TaskInstance).where(TaskInstance.id == instance_id)
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Task instance not found")

    instance.status = body.status
    if body.status == "COMPLETED":
        instance.completed_at = datetime.utcnow()
    else:
        instance.completed_at = None
    if body.notes is not None:
        instance.notes = body.notes
    if body.completed_by is not None:
        instance.completed_by = body.completed_by

    await db.commit()
    return {"instance_id": instance.id, "status": instance.status}


@router.post("/generate")
async def force_generate(db: AsyncSession = Depends(get_db)):
    """Manually trigger task instance generation for today."""
    count = await generate_due_tasks(db)
    return {"generated": count}
