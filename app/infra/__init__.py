"""Infrastructure blueprint (backup & maintenance)."""

from flask import Blueprint

bp = Blueprint('infra', __name__)

from app.infra import backup  # noqa
