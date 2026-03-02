"""Excel import engine blueprint."""

from flask import Blueprint

bp = Blueprint('import_engine', __name__)

from app.import_engine import routes  # noqa
