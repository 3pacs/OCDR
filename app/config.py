"""Flask application configuration."""

import os
import sys
from pathlib import Path

# Detect PyInstaller bundle (same pattern as ocdr/config.py)
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = BASE_DIR


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'ocdr-dev-key-change-in-prod')
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{BASE_DIR / "data" / "ocdr.db"}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = str(BASE_DIR / 'data' / 'uploads')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB
    BACKUP_DIR = os.environ.get('BACKUP_DIR', str(BASE_DIR / 'data' / 'backups'))
    IMPORT_BATCH_SIZE = 500


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    UPLOAD_FOLDER = '/tmp/ocdr_test_uploads'
    BACKUP_DIR = '/tmp/ocdr_test_backups'
