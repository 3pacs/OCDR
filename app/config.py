import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URI', 'sqlite:///ocdr.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    IMPORT_FOLDER = os.getenv('IMPORT_FOLDER', os.path.join(os.getcwd(), 'import'))
    EXPORT_FOLDER = os.getenv('EXPORT_FOLDER', os.path.join(os.getcwd(), 'export'))
    BACKUP_FOLDER = os.getenv('BACKUP_FOLDER', os.path.join(os.getcwd(), 'backup'))
    MONITOR_POLL_INTERVAL = int(os.getenv('MONITOR_POLL_INTERVAL', 30))
    CSV_EXPORT_INTERVAL = int(os.getenv('CSV_EXPORT_INTERVAL', 900))
    GADO_COST_PER_DOSE = float(os.getenv('GADO_COST_PER_DOSE', 50.00))
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB upload limit
