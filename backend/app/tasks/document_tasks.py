"""
Celery tasks for document ingestion.
These are stubs that delegate to the ingestion pipeline modules.
Full implementation is in Step 3 (document ingestion).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.config import settings
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.document_tasks.scan_schedule_folder", bind=True, max_retries=3)
def scan_schedule_folder(self):
    """Scan /data/schedules/ for new PDF files and trigger ingestion."""
    from app.ingestion.schedule_parser import process_schedule_pdf
    watch_dir = Path(settings.WATCH_SCHEDULES_DIR)
    processed_dir = watch_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = list(watch_dir.glob("*.pdf"))
    results = []
    for pdf_path in pdf_files:
        try:
            result = process_schedule_pdf.delay(str(pdf_path))
            results.append({"file": pdf_path.name, "task_id": result.id})
        except Exception as exc:
            results.append({"file": pdf_path.name, "error": str(exc)})
    return {"scanned": len(pdf_files), "results": results}


@celery_app.task(name="app.tasks.document_tasks.scan_eob_folder", bind=True, max_retries=3)
def scan_eob_folder(self):
    """Scan /data/eobs/ for new EOB PDF files and trigger ingestion."""
    from app.ingestion.eob_parser import process_eob_pdf
    watch_dir = Path(settings.WATCH_EOBS_DIR)
    processed_dir = watch_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = list(watch_dir.glob("*.pdf"))
    results = []
    for pdf_path in pdf_files:
        try:
            result = process_eob_pdf.delay(str(pdf_path))
            results.append({"file": pdf_path.name, "task_id": result.id})
        except Exception as exc:
            results.append({"file": pdf_path.name, "error": str(exc)})
    return {"scanned": len(pdf_files), "results": results}


@celery_app.task(name="app.tasks.document_tasks.scan_payment_folder", bind=True, max_retries=3)
def scan_payment_folder(self):
    """Scan /data/payments/ for new check images and trigger ingestion."""
    from app.ingestion.payment_parser import process_payment_image
    watch_dir = Path(settings.WATCH_PAYMENTS_DIR)
    processed_dir = watch_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    files = list(watch_dir.glob("*.pdf")) + list(watch_dir.glob("*.jpg")) + list(watch_dir.glob("*.png"))
    results = []
    for file_path in files:
        try:
            result = process_payment_image.delay(str(file_path))
            results.append({"file": file_path.name, "task_id": result.id})
        except Exception as exc:
            results.append({"file": file_path.name, "error": str(exc)})
    return {"scanned": len(files), "results": results}


@celery_app.task(name="app.tasks.document_tasks.backup_database", bind=True)
def backup_database(self):
    """Create a timestamped backup of the PostgreSQL database."""
    import subprocess
    from datetime import datetime

    backup_dir = Path(settings.BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"ocdr_backup_{timestamp}.sql.gz"

    if "postgresql" in settings.DATABASE_URL:
        # pg_dump → gzip
        try:
            db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
            cmd = f'pg_dump "{db_url}" | gzip > "{backup_file}"'
            subprocess.run(cmd, shell=True, check=True)
            # Remove old backups
            _cleanup_old_backups(backup_dir, settings.BACKUP_RETENTION_DAYS)
            return {"status": "success", "file": str(backup_file)}
        except subprocess.CalledProcessError as exc:
            return {"status": "error", "error": str(exc)}
    else:
        # SQLite — just copy the file
        db_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
        if os.path.exists(db_path):
            dest = backup_dir / f"ocdr_backup_{timestamp}.db"
            shutil.copy2(db_path, dest)
            _cleanup_old_backups(backup_dir, settings.BACKUP_RETENTION_DAYS)
            return {"status": "success", "file": str(dest)}
        return {"status": "skipped", "reason": "Database file not found"}


def _cleanup_old_backups(backup_dir: Path, retention_days: int) -> None:
    """Remove backup files older than retention_days."""
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    for f in backup_dir.iterdir():
        if f.is_file() and datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink()
