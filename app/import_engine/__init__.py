from flask import Blueprint

import_bp = Blueprint("import", __name__)

# Import route modules so they register their endpoints on import_bp
from app.import_engine import format_detector    # noqa: F401, E402
from app.import_engine import ai_assistant       # noqa: F401, E402
from app.import_engine import schedule_parser    # noqa: F401, E402
