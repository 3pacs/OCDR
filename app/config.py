import os
import secrets

basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


class Config:
    # Generate a random key if not set; production SHOULD set SECRET_KEY in env
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
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
    SCHEDULE_FOLDER = os.environ.get(
        "SCHEDULE_FOLDER", os.path.join(basedir, "schedule_data")
    )
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB max upload

    # LLM integration
    LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://localhost:11434")
    LLM_MODEL = os.environ.get("LLM_MODEL", "llama3")

    # Anthropic API (for AI-assisted import — only structural metadata sent, never PHI)
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
