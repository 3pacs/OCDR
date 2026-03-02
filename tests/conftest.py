"""Shared test fixtures for Flask web application tests."""

import os
import pytest

from app import create_app
from app.extensions import db as _db
from app.config import TestConfig


@pytest.fixture
def app():
    """Create a Flask app with test config (in-memory SQLite)."""
    app = create_app(TestConfig)
    yield app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def db(app):
    """Database session scoped to the test."""
    with app.app_context():
        yield _db
