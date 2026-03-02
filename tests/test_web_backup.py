"""Tests for backup system API (F-20)."""

import os
import tempfile

from app.config import TestConfig


class BackupTestConfig(TestConfig):
    """Test config that uses a real file-based SQLite for backup testing."""
    pass


def test_backup_status_empty(client):
    """GET /api/backup/status with no backups."""
    resp = client.get('/api/backup/status')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['total_backups'] == 0


def test_backup_history_empty(client):
    """GET /api/backup/history with no backups."""
    resp = client.get('/api/backup/history')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['total'] == 0
    assert data['backups'] == []


def test_backup_run_no_db_file(client):
    """POST /api/backup/run with in-memory DB returns 404."""
    resp = client.post('/api/backup/run')
    # In-memory SQLite has no file to back up
    assert resp.status_code == 404


def test_backup_full_cycle(tmp_path):
    """Full backup cycle: create DB file, back up, verify."""
    from app import create_app
    from app.extensions import db as _db

    db_path = str(tmp_path / 'test.db')
    backup_dir = str(tmp_path / 'backups')

    class FileDBConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_path}'
        BACKUP_DIR = backup_dir

    app = create_app(FileDBConfig)
    client = app.test_client()

    # Run backup
    resp = client.post('/api/backup/run')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'backup_path' in data
    assert 'sha256' in data
    assert data['size_bytes'] > 0
    assert os.path.exists(data['backup_path'])

    # Check status
    resp = client.get('/api/backup/status')
    assert resp.status_code == 200
    status = resp.get_json()
    assert status['total_backups'] == 1
    assert status['latest'] is not None

    # Check history
    resp = client.get('/api/backup/history')
    assert resp.status_code == 200
    history = resp.get_json()
    assert history['total'] == 1
    assert len(history['backups']) == 1
    assert len(history['backups'][0]['filename']) > 0
    assert history['backups'][0]['size_bytes'] > 0
