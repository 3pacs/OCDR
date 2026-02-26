"""F-20: Local Backup & Version History

Backs up ocdr.db with SHA256 integrity checking and retention policy:
  - 7 daily backups
  - 4 weekly backups
  - 12 monthly backups
"""
import os
import shutil
import hashlib
from datetime import datetime, timedelta
from flask import Blueprint, current_app, jsonify

backup_bp = Blueprint('backup', __name__)


def sha256_file(filepath):
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def run_backup(db_uri, backup_folder):
    """Run a backup of the SQLite database.

    Returns dict with backup path, size, and hash.
    """
    # Resolve DB path from URI
    db_path = db_uri.replace('sqlite:///', '')
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.getcwd(), 'instance', db_path)

    if not os.path.exists(db_path):
        raise FileNotFoundError(f'Database not found: {db_path}')

    os.makedirs(backup_folder, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f'ocdr_{timestamp}.db'
    backup_path = os.path.join(backup_folder, backup_name)

    shutil.copy2(db_path, backup_path)
    file_hash = sha256_file(backup_path)
    file_size = os.path.getsize(backup_path)

    # Write hash sidecar
    with open(backup_path + '.sha256', 'w') as f:
        f.write(f'{file_hash}  {backup_name}\n')

    return {
        'backup_path': backup_path,
        'size_bytes': file_size,
        'sha256': file_hash,
        'timestamp': timestamp,
    }


def prune_backups(backup_folder, daily=7, weekly=4, monthly=12):
    """Prune old backups according to retention policy.

    Keeps:
      - Last `daily` daily backups
      - Last `weekly` weekly backups (one per week)
      - Last `monthly` monthly backups (one per month)
    """
    if not os.path.isdir(backup_folder):
        return []

    backups = []
    for fname in os.listdir(backup_folder):
        if fname.startswith('ocdr_') and fname.endswith('.db'):
            fpath = os.path.join(backup_folder, fname)
            # Parse timestamp from filename: ocdr_YYYYMMDD_HHMMSS.db
            try:
                ts_str = fname[5:-3]  # strip 'ocdr_' and '.db'
                ts = datetime.strptime(ts_str, '%Y%m%d_%H%M%S')
                backups.append((ts, fpath))
            except ValueError:
                continue

    backups.sort(key=lambda x: x[0], reverse=True)

    if not backups:
        return []

    keep = set()
    removed = []

    # Keep last N daily
    for ts, path in backups[:daily]:
        keep.add(path)

    # Keep one per week for last N weeks
    now = datetime.now()
    for w in range(weekly):
        week_start = now - timedelta(weeks=w + 1)
        week_end = now - timedelta(weeks=w)
        for ts, path in backups:
            if week_start <= ts < week_end:
                keep.add(path)
                break

    # Keep one per month for last N months
    for m in range(monthly):
        target_month = now.month - m - 1
        target_year = now.year
        while target_month < 1:
            target_month += 12
            target_year -= 1
        for ts, path in backups:
            if ts.year == target_year and ts.month == target_month:
                keep.add(path)
                break

    # Remove backups not in keep set
    for ts, path in backups:
        if path not in keep:
            try:
                os.unlink(path)
                sha_file = path + '.sha256'
                if os.path.exists(sha_file):
                    os.unlink(sha_file)
                removed.append(os.path.basename(path))
            except OSError:
                pass

    return removed


@backup_bp.route('/backup/run', methods=['POST'])
def backup_now():
    """POST /api/backup/run - Run backup now"""
    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    backup_folder = current_app.config.get('BACKUP_FOLDER', 'backup')

    try:
        result = run_backup(db_uri, backup_folder)
        pruned = prune_backups(backup_folder)
        result['pruned'] = pruned
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@backup_bp.route('/backup/status', methods=['GET'])
def backup_status():
    """GET /api/backup/status - Backup status"""
    backup_folder = current_app.config.get('BACKUP_FOLDER', 'backup')

    if not os.path.isdir(backup_folder):
        return jsonify({'backups': 0, 'latest': None, 'folder': backup_folder})

    backups = sorted([
        f for f in os.listdir(backup_folder)
        if f.startswith('ocdr_') and f.endswith('.db')
    ], reverse=True)

    latest = None
    if backups:
        latest_path = os.path.join(backup_folder, backups[0])
        latest = {
            'filename': backups[0],
            'size_bytes': os.path.getsize(latest_path),
            'modified': datetime.fromtimestamp(
                os.path.getmtime(latest_path)
            ).isoformat(),
        }

    return jsonify({
        'backups': len(backups),
        'latest': latest,
        'folder': backup_folder,
    })


@backup_bp.route('/backup/history', methods=['GET'])
def backup_history():
    """GET /api/backup/history - List all backups"""
    backup_folder = current_app.config.get('BACKUP_FOLDER', 'backup')

    if not os.path.isdir(backup_folder):
        return jsonify({'backups': []})

    backups = []
    for fname in sorted(os.listdir(backup_folder), reverse=True):
        if fname.startswith('ocdr_') and fname.endswith('.db'):
            fpath = os.path.join(backup_folder, fname)
            backups.append({
                'filename': fname,
                'size_bytes': os.path.getsize(fpath),
                'modified': datetime.fromtimestamp(
                    os.path.getmtime(fpath)
                ).isoformat(),
            })

    return jsonify({'backups': backups})
