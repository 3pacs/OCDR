from flask import Blueprint

import_bp = Blueprint('import', __name__)

from app.import_engine import excel_importer  # noqa: E402, F401
