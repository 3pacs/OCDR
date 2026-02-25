import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
    DATABASE = os.environ.get('DATABASE', os.path.join(BASE_DIR, 'ocdr.db'))
