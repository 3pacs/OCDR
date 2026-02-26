"""Shared test fixtures for OCDR test suite."""
import pytest
from app import create_app
from app.models import db as _db


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-secret'
    BACKUP_FOLDER = '/tmp/ocdr_test_backup'


@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app(TestConfig)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def db(app):
    """Database session for testing."""
    with app.app_context():
        yield _db
