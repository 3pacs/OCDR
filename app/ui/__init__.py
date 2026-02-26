from flask import Blueprint

ui_bp = Blueprint('ui', __name__)

from app.ui import dashboard  # noqa: E402, F401
