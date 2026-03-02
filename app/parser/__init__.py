"""835 ERA parser blueprint."""

from flask import Blueprint

bp = Blueprint('parser', __name__)

from app.parser import routes  # noqa
