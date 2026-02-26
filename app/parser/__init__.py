from flask import Blueprint

parser_bp = Blueprint('parser', __name__)

from app.parser import era_835_parser  # noqa: E402, F401
