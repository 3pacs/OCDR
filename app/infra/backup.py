"""Local backup and version history API routes (F-20)."""

import os
import shutil
import hashlib
from datetime import datetime

from flask import jsonify, current_app

from app.infra import bp


def _sha256(filepath):
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def _get_db_path():
    """Extract the filesystem path from the SQLite URI."""
    uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    return uri.replace('sqlite:///', '')


def _list_backups():
    """Return list of backup file dicts, sorted newest-first."""
    backup_dir = current_app.config.get('BACKUP_DIR', 'data/backups')
    if not os.path.isdir(backup_dir):
        return []

    backups = []
    for fname in sorted(os.listdir(backup_dir), reverse=True):
        if not fname.startswith('ocdr_') or not fname.endswith('.db'):
            continue
        fpath = os.path.join(backup_dir, fname)
        # Parse timestamp from filename: ocdr_YYYYMMDD_HHMMSS.db
        try:
            ts_str = fname.replace('ocdr_', '').replace('.db', '')
            ts = datetime.strptime(ts_str, '%Y%m%d_%H%M%S')
        except ValueError:
            continue

        backups.append({
            'filename': fname,
            'path': fpath,
            'timestamp': ts.isoformat(),
            'size_bytes': os.path.getsize(fpath),
        })

    return backups


def _apply_retention(backup_dir):
    """Apply retention policy: keep 7 daily, 4 weekly, 12 monthly.

    Backups are sorted newest-first from _list_backups(). For each tier,
    the first (newest) backup per time bucket is kept. Then we keep the
    N most recent buckets per tier.
    """
    backups = _list_backups()
    if not backups:
        return

    keep = set()
    daily = {}
    weekly = {}
    monthly = {}

    # Backups are newest-first, so first seen per bucket = newest in that bucket
    for b in backups:
        ts = datetime.fromisoformat(b['timestamp'])
        day_key = ts.strftime('%Y-%m-%d')
        week_key = ts.strftime('%Y-W%W')
        month_key = ts.strftime('%Y-%m')

        if day_key not in daily:
            daily[day_key] = b['filename']
        if week_key not in weekly:
            weekly[week_key] = b['filename']
        if month_key not in monthly:
            monthly[month_key] = b['filename']

    # Keep the N most recent buckets (dict preserves insertion order,
    # and backups are newest-first, so slicing [:N] gives newest N)
    keep.update(list(daily.values())[:7])
    keep.update(list(weekly.values())[:4])
    keep.update(list(monthly.values())[:12])

    for b in backups:
        if b['filename'] not in keep:
            try:
                os.remove(b['path'])
            except OSError:
                pass


@bp.route('/backup/run', methods=['POST'])
def run_backup():
    """Create a new database backup."""
    db_path = _get_db_path()
    if not os.path.exists(db_path):
        return jsonify({'error': 'Database file not found'}), 404

    backup_dir = current_app.config.get('BACKUP_DIR', 'data/backups')
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f'ocdr_{timestamp}.db'
    backup_path = os.path.join(backup_dir, backup_name)

    try:
        shutil.copy2(db_path, backup_path)
    except Exception as e:
        return jsonify({'error': f'Backup failed: {str(e)}'}), 500

    sha = _sha256(backup_path)
    size = os.path.getsize(backup_path)

    _apply_retention(backup_dir)

    return jsonify({
        'backup_path': backup_path,
        'filename': backup_name,
        'size_bytes': size,
        'sha256': sha,
        'timestamp': datetime.now().isoformat(),
    }), 201


@bp.route('/backup/status', methods=['GET'])
def backup_status():
    """Return latest backup info and overall stats."""
    backups = _list_backups()

    if not backups:
        return jsonify({
            'latest': None,
            'total_backups': 0,
            'total_size_bytes': 0,
        })

    return jsonify({
        'latest': backups[0],
        'total_backups': len(backups),
        'total_size_bytes': sum(b['size_bytes'] for b in backups),
    })


@bp.route('/backup/history', methods=['GET'])
def backup_history():
    """List all backups with metadata."""
    backups = _list_backups()
    return jsonify({
        'backups': backups,
        'total': len(backups),
    })
