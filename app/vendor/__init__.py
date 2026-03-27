from flask import Blueprint

vendor_bp = Blueprint('vendor', __name__)

from app.vendor import routes  # noqa: E402, F401
