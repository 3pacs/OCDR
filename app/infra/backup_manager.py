"""Local Backup & Version History (F-20).

Backs up ocdr.db with SHA256 integrity check.
Retention: 7 daily, 4 weekly, 12 monthly.
"""

import hashlib
import os
import shutil
from datetime import datetime, timedelta
from glob import glob


def _sha256(filepath):
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def run_backup(app=None, db_path=None, backup_dir=None):
    """Run a backup of the database.

    Args:
        app: Flask app (for config)
        db_path: Direct path to database file
        backup_dir: Direct path to backup directory

    Returns:
        dict: {filepath, size, sha256, timestamp}
    """
    if app and not db_path:
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if "sqlite:///" in uri:
            db_path = uri.replace("sqlite:///", "")
    if not db_path:
        db_path = "ocdr.db"

    if app and not backup_dir:
        backup_dir = app.config.get("BACKUP_FOLDER", "backup")
    if not backup_dir:
        backup_dir = "backup"

    os.makedirs(backup_dir, exist_ok=True)

    if not os.path.exists(db_path):
        return {"error": f"Database not found: {db_path}"}

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"ocdr_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)

    shutil.copy2(db_path, backup_path)
    file_hash = _sha256(backup_path)
    file_size = os.path.getsize(backup_path)

    # Write hash file
    hash_path = backup_path + ".sha256"
    with open(hash_path, "w") as f:
        f.write(f"{file_hash}  {backup_filename}\n")

    # Apply retention policy
    _apply_retention(backup_dir)

    return {
        "filepath": backup_path,
        "filename": backup_filename,
        "size": file_size,
        "sha256": file_hash,
        "timestamp": timestamp,
    }


def verify_backup(backup_path):
    """Verify backup integrity using SHA256."""
    if not os.path.exists(backup_path):
        return {"valid": False, "error": "File not found"}

    current_hash = _sha256(backup_path)
    hash_path = backup_path + ".sha256"

    if os.path.exists(hash_path):
        with open(hash_path, "r") as f:
            stored_hash = f.read().strip().split()[0]
        return {
            "valid": current_hash == stored_hash,
            "current_hash": current_hash,
            "stored_hash": stored_hash,
        }

    return {"valid": True, "hash": current_hash, "note": "No stored hash to verify against"}


def get_backup_history(backup_dir=None):
    """List all backups with metadata."""
    if not backup_dir:
        backup_dir = "backup"

    if not os.path.isdir(backup_dir):
        return {"backups": [], "total": 0}

    backups = []
    for f in sorted(glob(os.path.join(backup_dir, "ocdr_*.db")), reverse=True):
        filename = os.path.basename(f)
        backups.append({
            "filename": filename,
            "filepath": f,
            "size": os.path.getsize(f),
            "modified": datetime.fromtimestamp(os.path.getmtime(f)).isoformat(),
            "has_hash": os.path.exists(f + ".sha256"),
        })

    total_size = sum(b["size"] for b in backups)
    return {
        "backups": backups,
        "total": len(backups),
        "total_size": total_size,
    }


def _apply_retention(backup_dir, daily_keep=7, weekly_keep=4, monthly_keep=12):
    """Apply retention policy: 7 daily, 4 weekly, 12 monthly."""
    files = sorted(glob(os.path.join(backup_dir, "ocdr_*.db")))
    if len(files) <= daily_keep:
        return

    now = datetime.utcnow()
    keep = set()

    # Parse timestamps from filenames and categorize
    dated_files = []
    for f in files:
        basename = os.path.basename(f)
        try:
            ts_str = basename.replace("ocdr_", "").replace(".db", "")
            ts = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            dated_files.append((ts, f))
        except ValueError:
            keep.add(f)  # Keep files we can't parse

    dated_files.sort(key=lambda x: x[0], reverse=True)

    # Keep most recent N daily
    for ts, f in dated_files[:daily_keep]:
        keep.add(f)

    # Keep one per week for weekly_keep weeks
    weeks_seen = set()
    for ts, f in dated_files:
        week_key = ts.strftime("%Y-W%W")
        if week_key not in weeks_seen and len(weeks_seen) < weekly_keep:
            keep.add(f)
            weeks_seen.add(week_key)

    # Keep one per month for monthly_keep months
    months_seen = set()
    for ts, f in dated_files:
        month_key = ts.strftime("%Y-%m")
        if month_key not in months_seen and len(months_seen) < monthly_keep:
            keep.add(f)
            months_seen.add(month_key)

    # Delete files not in keep set
    for ts, f in dated_files:
        if f not in keep:
            try:
                os.remove(f)
                hash_file = f + ".sha256"
                if os.path.exists(hash_file):
                    os.remove(hash_file)
            except OSError:
                pass
