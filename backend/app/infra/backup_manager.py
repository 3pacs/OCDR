"""
Local Backup & Version History (F-20).

Backs up the PostgreSQL database via pg_dump and manages retention policy.
Retention: 7 daily, 4 weekly, 12 monthly.
SHA256 integrity check on each backup.
"""

import hashlib
import logging
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

BACKUP_DIR = os.environ.get("BACKUP_DIR", "/app/data/backups")
RETENTION_DAILY = 7
RETENTION_WEEKLY = 4
RETENTION_MONTHLY = 12


def _sha256(filepath: str) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def run_backup() -> dict:
    """
    Run a PostgreSQL backup using pg_dump.

    Returns dict with backup_path, size_bytes, sha256.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"ocdr_{timestamp}.sql"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    # Parse database URL for pg_dump
    db_url = settings.DATABASE_URL_SYNC
    # Format: postgresql://user:pass@host:port/dbname
    try:
        # Extract components
        url_part = db_url.replace("postgresql://", "")
        user_pass, host_db = url_part.split("@", 1)
        user, password = user_pass.split(":", 1)
        host_port, dbname = host_db.split("/", 1)
        if ":" in host_port:
            host, port = host_port.split(":", 1)
        else:
            host, port = host_port, "5432"
    except ValueError:
        raise RuntimeError(f"Could not parse DATABASE_URL_SYNC for backup")

    env = os.environ.copy()
    env["PGPASSWORD"] = password

    cmd = [
        "pg_dump",
        "-h", host,
        "-p", port,
        "-U", user,
        "-d", dbname,
        "-f", backup_path,
        "--no-owner",
        "--no-acl",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {result.stderr}")

    size_bytes = os.path.getsize(backup_path)
    sha256 = _sha256(backup_path)

    logger.info(f"Backup created: {backup_path} ({size_bytes} bytes, SHA256: {sha256[:16]}...)")

    # Run retention cleanup
    _enforce_retention()

    return {
        "backup_path": backup_path,
        "filename": backup_filename,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "timestamp": timestamp,
    }


def _enforce_retention():
    """Remove old backups per retention policy."""
    if not os.path.isdir(BACKUP_DIR):
        return

    backups = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.startswith("ocdr_") and f.endswith(".sql")],
        reverse=True,
    )

    if len(backups) <= RETENTION_DAILY:
        return  # Not enough to prune

    now = datetime.now()
    keep = set()

    # Keep last N daily
    for b in backups[:RETENTION_DAILY]:
        keep.add(b)

    # Keep weekly (one per week for RETENTION_WEEKLY weeks)
    for weeks_ago in range(RETENTION_WEEKLY):
        target = now - timedelta(weeks=weeks_ago)
        for b in backups:
            try:
                ts = datetime.strptime(b[5:20], "%Y%m%d_%H%M%S")
                if ts.isocalendar()[1] == target.isocalendar()[1] and ts.year == target.year:
                    keep.add(b)
                    break
            except ValueError:
                continue

    # Keep monthly (one per month for RETENTION_MONTHLY months)
    for months_ago in range(RETENTION_MONTHLY):
        target_month = now.month - months_ago
        target_year = now.year
        while target_month <= 0:
            target_month += 12
            target_year -= 1
        for b in backups:
            try:
                ts = datetime.strptime(b[5:20], "%Y%m%d_%H%M%S")
                if ts.month == target_month and ts.year == target_year:
                    keep.add(b)
                    break
            except ValueError:
                continue

    # Remove backups not in keep set
    for b in backups:
        if b not in keep:
            filepath = os.path.join(BACKUP_DIR, b)
            try:
                os.remove(filepath)
                logger.info(f"Pruned old backup: {b}")
            except OSError as e:
                logger.warning(f"Could not remove {b}: {e}")


def get_backup_history() -> list[dict]:
    """List all backups with metadata."""
    if not os.path.isdir(BACKUP_DIR):
        return []

    backups = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if f.startswith("ocdr_") and f.endswith(".sql"):
            fpath = os.path.join(BACKUP_DIR, f)
            backups.append({
                "filename": f,
                "path": fpath,
                "size_bytes": os.path.getsize(fpath),
                "sha256": _sha256(fpath),
                "created": datetime.fromtimestamp(os.path.getmtime(fpath)).isoformat(),
            })
    return backups
