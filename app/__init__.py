import os
import sqlite3
import time

from flask import Flask, g, jsonify

from app.config import Config
from app.models import db

_start_time = time.time()


def get_db():
    """Get a raw sqlite3 connection for complex queries.

    Used by modules that need raw SQL (denial_tracker, duplicate_detector,
    secondary_followup) alongside the SQLAlchemy ORM.
    """
    from flask import current_app
    if 'raw_db' not in g:
        db_path = current_app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        g.raw_db = sqlite3.connect(db_path)
        g.raw_db.row_factory = sqlite3.Row
    return g.raw_db


def create_app(config_class=Config):
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates'),
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'),
    )
    app.config.from_object(config_class)

    db.init_app(app)

    from flask_migrate import Migrate
    Migrate(app, db)

    # Register blueprints — Sprint 1
    from app.import_engine import import_bp
    app.register_blueprint(import_bp, url_prefix='/api/import')

    from app.parser import parser_bp
    app.register_blueprint(parser_bp, url_prefix='/api')

    from app.revenue.underpayment_detector import underpayment_bp
    app.register_blueprint(underpayment_bp, url_prefix='/api')

    from app.revenue.filing_deadlines import filing_bp
    app.register_blueprint(filing_bp, url_prefix='/api')

    from app.infra.backup_manager import backup_bp
    app.register_blueprint(backup_bp, url_prefix='/api')

    from app.ui import ui_bp
    app.register_blueprint(ui_bp)

    # Register blueprints — Sprint 2 (denial tracking, secondary, duplicates)
    from app.revenue.denial_tracker import denial_bp
    app.register_blueprint(denial_bp, url_prefix='/api')

    from app.revenue.secondary_followup import secondary_bp
    app.register_blueprint(secondary_bp, url_prefix='/api')

    from app.revenue.duplicate_detector import duplicate_bp
    app.register_blueprint(duplicate_bp, url_prefix='/api')

    # Register blueprints — Analytics
    from app.analytics.post_import import analysis_bp
    app.register_blueprint(analysis_bp, url_prefix='/api')

    # Register blueprints — Vendor connectors
    from app.vendor import vendor_bp
    app.register_blueprint(vendor_bp, url_prefix='/api/vendor')

    @app.teardown_appcontext
    def close_raw_db(exception):
        raw_db = g.pop('raw_db', None)
        if raw_db is not None:
            raw_db.close()

    @app.route('/health')
    def health():
        from app.models import BillingRecord
        db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        db_size = 0
        if os.path.exists(db_path):
            db_size = os.path.getsize(db_path)
        record_count = BillingRecord.query.count()
        uptime = int(time.time() - _start_time)
        return jsonify({
            'status': 'ok',
            'db_size': db_size,
            'record_count': record_count,
            'uptime_seconds': uptime,
        })

    with app.app_context():
        db.create_all()

    return app
