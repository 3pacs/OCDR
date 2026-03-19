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

    from app.analytics.post_import import analysis_bp
    app.register_blueprint(analysis_bp, url_prefix="/api")

    # ── CORS for local network access ───────────────────────────
    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin", "")
        if origin and (
            origin.startswith("http://localhost") or
            origin.startswith("http://127.0.0.1") or
            origin.startswith("http://192.168.") or
            origin.startswith("http://10.")
        ):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    # ── Error handlers ──────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not found"}), 404
        from flask import render_template as rt
        return rt("404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error(f"Internal error: {e}")
        if request.path.startswith("/api/"):
            return jsonify({"error": "Internal server error"}), 500
        from flask import render_template as rt
        return rt("500.html"), 500

    # ── SQLite WAL mode for concurrent reads during writes ──
    _enable_wal_mode(app)

    # ── Rate limiting ────────────────────────────────────────
    _init_rate_limiting(app)

    # ── Ensure required directories ────────────────────────────
    with app.app_context():
        _ensure_directories(app)
        _apply_sqlite_wal(app)
        db.create_all()
        _auto_migrate_missing_columns(app)
        _backfill_charge_categories()
        _backfill_era_payments()
        _seed_lookup_tables()
        _ensure_default_admin()
        _init_ai_logs(app)
        _auto_backup_on_startup(app)

    return app


def _enable_wal_mode(app):
    """Register SQLite PRAGMA event listener for every new connection.

    WAL (Write-Ahead Logging) allows concurrent reads while a write
    transaction is in progress, preventing 'database is locked' errors
    when long-running imports overlap with dashboard/status queries.
    """
    from sqlalchemy import event as sa_event

    with app.app_context():
        @sa_event.listens_for(db.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")  # 30 seconds
            cursor.execute("PRAGMA synchronous=NORMAL")  # safe with WAL
            cursor.close()


def _apply_sqlite_wal(app):
    """Apply WAL mode to existing database (runs once at startup)."""
    from sqlalchemy import text
    try:
        result = db.session.execute(text("PRAGMA journal_mode=WAL"))
        mode = result.scalar()
        app.logger.info(f"SQLite journal mode: {mode}")
    except Exception as e:
        app.logger.debug(f"WAL mode setup skipped: {e}")


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


def _auto_migrate_missing_columns(app):
    """Detect and add any columns defined in SQLAlchemy models but missing from SQLite.

    This fixes schema drift that occurs when new columns are added to models
    after the initial db.create_all() — SQLite's CREATE TABLE IF NOT EXISTS
    won't add new columns to existing tables.
    """
    from sqlalchemy import text, inspect as sa_inspect

    inspector = sa_inspect(db.engine)
    existing_tables = inspector.get_table_names()

    # Map SQLAlchemy types to SQLite type strings
    type_map = {
        'INTEGER': 'INTEGER',
        'TEXT': 'TEXT',
        'VARCHAR': 'TEXT',
        'FLOAT': 'REAL',
        'REAL': 'REAL',
        'BOOLEAN': 'BOOLEAN',
        'DATE': 'DATE',
        'DATETIME': 'DATETIME',
        'NUMERIC': 'NUMERIC',
    }

    altered = []

    for table_name, table in db.metadata.tables.items():
        if table_name not in existing_tables:
            continue  # db.create_all() handles new tables

        existing_cols = {col['name'] for col in inspector.get_columns(table_name)}

        for col in table.columns:
            if col.name in existing_cols:
                continue

            # Determine SQLite type
            sa_type = str(col.type).upper().split('(')[0]
            sqlite_type = type_map.get(sa_type, 'TEXT')

            # Determine default value
            default_clause = ''
            if col.default is not None:
                val = col.default.arg
                if callable(val):
                    default_clause = ''  # dynamic defaults (like _utcnow) can't be set in DDL
                elif isinstance(val, bool):
                    default_clause = f' DEFAULT {1 if val else 0}'
                elif isinstance(val, (int, float)):
                    default_clause = f' DEFAULT {val}'
                elif isinstance(val, str):
                    default_clause = f" DEFAULT '{val}'"

            sql = f'ALTER TABLE {table_name} ADD COLUMN {col.name} {sqlite_type}{default_clause}'
            try:
                db.session.execute(text(sql))
                altered.append(f'{table_name}.{col.name}')
            except Exception as e:
                # Column might already exist (race condition) or other error
                app.logger.debug(f'Auto-migrate skip {table_name}.{col.name}: {e}')

    if altered:
        db.session.commit()
        app.logger.info(f'Auto-migration: added {len(altered)} missing column(s): {", ".join(altered)}')


def _ensure_directories(app):
    """Create all required directories on startup."""
    for folder_key in ("UPLOAD_FOLDER", "EXPORT_FOLDER", "BACKUP_FOLDER",
                        "SCHEDULE_FOLDER", "AI_LOG_FOLDER"):
        folder = app.config.get(folder_key)
        if folder:
            os.makedirs(folder, exist_ok=True)


def _backfill_charge_categories():
    """One-time backfill: set charge_category on existing billing records.

    Infers from gado_used and is_psma flags. Only touches records where
    charge_category is NULL (won't overwrite manually set values).
    """
    from sqlalchemy import text
    try:
        # Check if the column exists yet
        result = db.session.execute(text(
            "SELECT COUNT(*) FROM billing_records WHERE charge_category IS NULL"
        )).scalar()
        if result == 0:
            return  # Nothing to backfill

        db.session.execute(text(
            "UPDATE billing_records SET charge_category = 'WITH_CONTRAST' "
            "WHERE charge_category IS NULL AND gado_used = 1 AND modality IN ('HMRI', 'OPEN')"
        ))
        db.session.execute(text(
            "UPDATE billing_records SET charge_category = 'PSMA' "
            "WHERE charge_category IS NULL AND is_psma = 1 AND modality = 'PET'"
        ))
        db.session.execute(text(
            "UPDATE billing_records SET charge_category = 'STANDARD' "
            "WHERE charge_category IS NULL"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _backfill_era_payments():
    """One-time backfill: flow ERA paid amounts to matched billing records.

    For billing records that have a matched ERA claim line but no era_paid_amount,
    copy the paid_amount from the ERA claim.
    """
    from sqlalchemy import text
    try:
        result = db.session.execute(text(
            "SELECT COUNT(*) FROM billing_records b "
            "JOIN era_claim_lines e ON e.matched_billing_id = b.id "
            "WHERE b.era_paid_amount IS NULL AND e.paid_amount IS NOT NULL"
        )).scalar()
        if result == 0:
            return

        # Update era_paid_amount from matched ERA claims
        db.session.execute(text(
            "UPDATE billing_records SET era_paid_amount = ("
            "  SELECT e.paid_amount FROM era_claim_lines e "
            "  WHERE e.matched_billing_id = billing_records.id "
            "  ORDER BY e.paid_amount DESC LIMIT 1"
            ") WHERE era_paid_amount IS NULL AND id IN ("
            "  SELECT matched_billing_id FROM era_claim_lines "
            "  WHERE matched_billing_id IS NOT NULL AND paid_amount IS NOT NULL"
            ")"
        ))

        # Update payment_method from ERA payment header
        db.session.execute(text(
            "UPDATE billing_records SET payment_method = ("
            "  SELECT CASE ep.payment_method "
            "    WHEN 'CHK' THEN 'CHECK' "
            "    WHEN 'ACH' THEN 'EFT' "
            "    WHEN 'FWT' THEN 'WIRE' "
            "    ELSE ep.payment_method "
            "  END "
            "  FROM era_claim_lines e "
            "  JOIN era_payments ep ON ep.id = e.era_payment_id "
            "  WHERE e.matched_billing_id = billing_records.id "
            "  LIMIT 1"
            ") WHERE payment_method IS NULL AND id IN ("
            "  SELECT matched_billing_id FROM era_claim_lines "
            "  WHERE matched_billing_id IS NOT NULL"
            ")"
        ))

        # Update billed_amount from ERA
        db.session.execute(text(
            "UPDATE billing_records SET billed_amount = ("
            "  SELECT e.billed_amount FROM era_claim_lines e "
            "  WHERE e.matched_billing_id = billing_records.id "
            "  ORDER BY e.billed_amount DESC LIMIT 1"
            ") WHERE (billed_amount IS NULL OR billed_amount = 0) AND id IN ("
            "  SELECT matched_billing_id FROM era_claim_lines "
            "  WHERE matched_billing_id IS NOT NULL AND billed_amount IS NOT NULL"
            ")"
        ))

        # Update adjustment_amount from ERA
        db.session.execute(text(
            "UPDATE billing_records SET adjustment_amount = ("
            "  SELECT e.cas_adjustment_amount FROM era_claim_lines e "
            "  WHERE e.matched_billing_id = billing_records.id "
            "  ORDER BY e.cas_adjustment_amount DESC LIMIT 1"
            ") WHERE (adjustment_amount IS NULL OR adjustment_amount = 0) AND id IN ("
            "  SELECT matched_billing_id FROM era_claim_lines "
            "  WHERE matched_billing_id IS NOT NULL AND cas_adjustment_amount IS NOT NULL"
            ")"
        ))

        db.session.commit()
    except Exception:
        db.session.rollback()


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


def _init_ai_logs(app):
    """Initialize AI communication log directory and instruction files."""
    try:
        from app.llm.ai_log import write_ai_instructions, log_system_event
        write_ai_instructions()
        log_system_event("app_startup", {
            "status": "initialized",
            "ai_log_folder": app.config.get("AI_LOG_FOLDER", "ai_logs"),
        })
        app.logger.info("AI communication logs initialized")
    except Exception as e:
        app.logger.debug(f"AI log init skipped: {e}")


def _init_rate_limiting(app):
    """Install global rate limiting."""
    try:
        from app.infra.rate_limiter import init_rate_limiting
        init_rate_limiting(
            app,
            default_write_rate=app.config.get("RATE_LIMIT_WRITE", "30/minute"),
            default_read_rate=app.config.get("RATE_LIMIT_READ", "120/minute"),
        )
        app.logger.info("Rate limiting initialized")
    except Exception as e:
        app.logger.debug(f"Rate limiting init skipped: {e}")


def _auto_backup_on_startup(app):
    """Run an automatic backup on startup if last backup is >24h old."""
    try:
        from app.infra.backup_manager import run_backup, get_backup_history
        backup_dir = app.config.get("BACKUP_FOLDER", "backup")
        history = get_backup_history(backup_dir)

        # Check if we need a backup (no backups or last one >24h ago)
        need_backup = True
        if history["backups"]:
            from datetime import datetime as dt
            last_modified = history["backups"][0].get("modified", "")
            try:
                last_dt = dt.fromisoformat(last_modified)
                age_hours = (dt.utcnow() - last_dt).total_seconds() / 3600
                if age_hours < 24:
                    need_backup = False
            except (ValueError, TypeError):
                pass

        if need_backup:
            result = run_backup(app=app)
            if "error" not in result:
                app.logger.info(f"Auto-backup created: {result.get('filename')}")
            else:
                app.logger.debug(f"Auto-backup skipped: {result.get('error')}")
        else:
            app.logger.debug("Auto-backup: recent backup exists, skipping")
    except Exception as e:
        app.logger.debug(f"Auto-backup skipped: {e}")


def _ensure_default_admin():
    """Create default admin user if no users exist."""
    if User.query.first() is not None:
        return
    admin = User(username="admin", role="admin")
    admin.set_password("admin")
    db.session.add(admin)
    db.session.commit()
