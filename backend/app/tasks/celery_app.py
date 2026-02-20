"""
Celery application configuration with periodic tasks.
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "ocdr",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.document_tasks",
        "app.tasks.sync_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/New_York",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# ── Periodic schedule ─────────────────────────────────────────────────────────
celery_app.conf.beat_schedule = {
    # Watch for new schedule PDFs every 2 minutes
    "watch-schedule-folder": {
        "task": "app.tasks.document_tasks.scan_schedule_folder",
        "schedule": 120,  # seconds
    },
    # Watch for new EOB PDFs every 5 minutes
    "watch-eob-folder": {
        "task": "app.tasks.document_tasks.scan_eob_folder",
        "schedule": 300,
    },
    # Watch for new payment images every 5 minutes
    "watch-payment-folder": {
        "task": "app.tasks.document_tasks.scan_payment_folder",
        "schedule": 300,
    },
    # Sync with Office Ally (configurable interval)
    "sync-office-ally-claims": {
        "task": "app.tasks.sync_tasks.sync_office_ally_claim_status",
        "schedule": settings.OFFICE_ALLY_SYNC_INTERVAL_HOURS * 3600,
    },
    # Daily DB backup at 2 AM
    "daily-backup": {
        "task": "app.tasks.document_tasks.backup_database",
        "schedule": crontab(hour=2, minute=0),
    },
}
