import logging
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_login import LoginManager
from flask_migrate import Migrate

from app.config import Config
from app.models import db, User, Modality, ScanType

migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "ui.login"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def create_app(config_class=Config, **config_overrides):
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )
    app.config.from_object(config_class)
    if config_overrides:
        app.config.update(config_overrides)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # ── Structured logging ──────────────────────────────────────
    _setup_logging(app)

    # Register blueprints
    from app.ui.dashboard import ui_bp
    from app.ui.api import api_bp
    from app.import_engine import import_bp
    from app.vendor import vendor_bp

    app.register_blueprint(ui_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(import_bp, url_prefix="/api/import")
    app.register_blueprint(vendor_bp, url_prefix="/api/vendor")

    # ── Error handlers ──────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not found"}), 404
        return (jsonify({"error": "Not found"}), 404)

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error(f"Internal error: {e}")
        if request.path.startswith("/api/"):
            return jsonify({"error": "Internal server error"}), 500
        return (jsonify({"error": "Internal server error"}), 500)

    # ── Ensure required directories ────────────────────────────
    with app.app_context():
        _ensure_directories(app)
        db.create_all()
        _seed_lookup_tables()
        _ensure_default_admin()

    return app


def _setup_logging(app):
    """Configure structured logging."""
    log_level = logging.DEBUG if app.debug else logging.INFO
    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)
    app.logger.setLevel(log_level)

    # Log directory for file-based logging
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.FileHandler(os.path.join(log_dir, "ocdr.log"))
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    app.logger.addHandler(file_handler)


def _ensure_directories(app):
    """Create all required directories on startup."""
    for folder_key in ("UPLOAD_FOLDER", "EXPORT_FOLDER", "BACKUP_FOLDER", "SCHEDULE_FOLDER"):
        folder = app.config.get(folder_key)
        if folder:
            os.makedirs(folder, exist_ok=True)


def _seed_lookup_tables():
    """Populate lookup tables with initial data if empty."""
    if Modality.query.first() is not None:
        return

    modalities = [
        ("CT", "CT Scan", "CT_PET_GROUP", 1),
        ("HMRI", "High-Field MRI", "MRI_GROUP", 2),
        ("PET", "PET/CT Scan", "CT_PET_GROUP", 3),
        ("BONE", "Bone Density / DEXA", "OTHER_GROUP", 4),
        ("OPEN", "Open MRI", "MRI_GROUP", 5),
        ("DX", "Digital X-Ray", "OTHER_GROUP", 6),
        ("GH", "General Health", "OTHER_GROUP", 7),
    ]
    for code, name, cat, order in modalities:
        db.session.add(Modality(code=code, display_name=name, category=cat, sort_order=order))

    scan_types = [
        "ABDOMEN", "CHEST", "HEAD", "CERVICAL", "LUMBAR",
        "PELVIS", "SINUS", "THORACIC", "KNEE", "SHOULDER",
        "BRAIN", "SPINE", "HIP", "ANKLE", "WRIST",
    ]
    for i, name in enumerate(scan_types):
        db.session.add(ScanType(code=name, display_name=name.title(), sort_order=i))

    # Common CAS reason codes
    from app.models import CasReasonCode
    cas_codes = [
        ("4", "CO", "The procedure code is inconsistent with the modifier", "CODING"),
        ("45", "CO", "Charge exceeds fee schedule/maximum allowable", "FEE_SCHEDULE"),
        ("96", "CO", "Non-covered charge(s)", "COVERAGE"),
        ("97", "CO", "Payment adjusted: benefit for this service not provided", "COVERAGE"),
        ("197", "CO", "Precertification/authorization/notification absent", "AUTHORIZATION"),
        ("16", "CO", "Claim/service lacks information needed for adjudication", "DOCUMENTATION"),
        ("18", "CO", "Exact duplicate claim/service", "DUPLICATE"),
        ("29", "CO", "The time limit for filing has expired", "TIMELY_FILING"),
        ("1", "PR", "Deductible amount", "PATIENT_RESPONSIBILITY"),
        ("2", "PR", "Coinsurance amount", "PATIENT_RESPONSIBILITY"),
        ("3", "PR", "Co-payment amount", "PATIENT_RESPONSIBILITY"),
        ("50", "CO", "Non-covered service because not deemed medically necessary", "MEDICAL_NECESSITY"),
    ]
    for code, group, desc, cat in cas_codes:
        db.session.add(CasReasonCode(code=code, group_code=group, description=desc, category=cat))

    db.session.commit()


def _ensure_default_admin():
    """Create default admin user if no users exist."""
    if User.query.first() is not None:
        return
    admin = User(username="admin", role="admin")
    admin.set_password("admin")
    db.session.add(admin)
    db.session.commit()
