import os

basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "ocdr-dev-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(basedir, 'ocdr.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER", os.path.join(basedir, "uploads")
    )
    EXPORT_FOLDER = os.environ.get(
        "EXPORT_FOLDER", os.path.join(basedir, "export")
    )
    BACKUP_FOLDER = os.environ.get(
        "BACKUP_FOLDER", os.path.join(basedir, "backup")
    )
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB max upload
