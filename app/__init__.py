import sqlite3
from flask import Flask, g
from app.config import Config


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(Flask.current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA journal_mode=WAL')
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db(app):
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA_SQL)
        db.commit()


def create_app(config_class=Config):
    app = Flask(
        __name__,
        template_folder='../templates',
        static_folder='../static',
    )
    app.config.from_object(config_class)
    Flask.current_app = app

    app.teardown_appcontext(close_db)

    from app.revenue.denial_tracker import denial_bp
    from app.revenue.underpayment_detector import underpayment_bp
    from app.revenue.filing_deadlines import filing_bp
    from app.revenue.secondary_followup import secondary_bp
    from app.revenue.duplicate_detector import duplicate_bp

    app.register_blueprint(denial_bp)
    app.register_blueprint(underpayment_bp)
    app.register_blueprint(filing_bp)
    app.register_blueprint(secondary_bp)
    app.register_blueprint(duplicate_bp)

    init_db(app)

    return app


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS payers (
    code            TEXT PRIMARY KEY,
    display_name    TEXT,
    filing_deadline_days INTEGER NOT NULL DEFAULT 180,
    expected_has_secondary BOOLEAN DEFAULT FALSE,
    alert_threshold_pct REAL DEFAULT 0.25
);

CREATE TABLE IF NOT EXISTS fee_schedule (
    payer_code  TEXT NOT NULL,
    modality    TEXT NOT NULL,
    expected_rate REAL NOT NULL,
    underpayment_threshold REAL DEFAULT 0.80,
    PRIMARY KEY (payer_code, modality)
);

CREATE TABLE IF NOT EXISTS billing_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_name        TEXT NOT NULL,
    referring_doctor    TEXT NOT NULL,
    scan_type           TEXT NOT NULL,
    gado_used           BOOLEAN DEFAULT FALSE,
    insurance_carrier   TEXT NOT NULL,
    modality            TEXT NOT NULL,
    service_date        DATE NOT NULL,
    primary_payment     REAL DEFAULT 0,
    secondary_payment   REAL DEFAULT 0,
    total_payment       REAL DEFAULT 0,
    extra_charges       REAL DEFAULT 0,
    reading_physician   TEXT,
    patient_id          INTEGER,
    description         TEXT,
    is_psma             BOOLEAN DEFAULT FALSE,
    denial_status       TEXT DEFAULT NULL,
    denial_reason_code  TEXT,
    era_claim_id        TEXT,
    appeal_deadline     DATE,
    billed_amount       REAL DEFAULT 0,
    import_source       TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_billing_denial_status ON billing_records(denial_status);
CREATE INDEX IF NOT EXISTS idx_billing_carrier ON billing_records(insurance_carrier);
CREATE INDEX IF NOT EXISTS idx_billing_modality ON billing_records(modality);
CREATE INDEX IF NOT EXISTS idx_billing_service_date ON billing_records(service_date);
CREATE INDEX IF NOT EXISTS idx_billing_total_payment ON billing_records(total_payment);
CREATE INDEX IF NOT EXISTS idx_billing_appeal_deadline ON billing_records(appeal_deadline);

CREATE TABLE IF NOT EXISTS era_payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    filename        TEXT NOT NULL,
    check_eft_number TEXT,
    payment_amount  REAL,
    payment_date    DATE,
    payment_method  TEXT,
    payer_name      TEXT,
    parsed_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS era_claim_lines (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    era_payment_id      INTEGER NOT NULL REFERENCES era_payments(id),
    claim_id            TEXT,
    claim_status        TEXT,
    billed_amount       REAL,
    paid_amount         REAL,
    patient_name_835    TEXT,
    service_date_835    DATE,
    cpt_code            TEXT,
    cas_group_code      TEXT,
    cas_reason_code     TEXT,
    cas_adjustment_amount REAL,
    match_confidence    REAL,
    matched_billing_id  INTEGER REFERENCES billing_records(id)
);
"""
