import os

basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{os.path.join(basedir, "instance", "ocdr.db")}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
    EXPORT_FOLDER = os.environ.get('EXPORT_FOLDER', os.path.join(basedir, 'export'))
    BACKUP_FOLDER = os.path.join(basedir, 'backups')
    WATCH_FOLDER = os.environ.get('WATCH_FOLDER', os.path.join(basedir, 'watch'))
