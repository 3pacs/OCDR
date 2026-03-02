"""Revenue analysis blueprint (underpayments + filing deadlines)."""

from flask import Blueprint

bp = Blueprint('revenue', __name__)

from app.revenue import underpayments  # noqa
from app.revenue import filing_deadlines  # noqa
