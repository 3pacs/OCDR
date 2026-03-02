"""Shared Flask extensions (initialized once, used everywhere)."""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
