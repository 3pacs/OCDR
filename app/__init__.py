"""Flask application factory for OCDR web application."""

import os
import time
import json
from datetime import date, datetime
from decimal import Decimal

from flask import Flask, jsonify
from app.extensions import db
from app.config import Config

_start_time = time.time()


class _JSONProvider(Flask.json_provider_class):
    """Custom JSON provider that handles Decimal and date types."""

    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return super().default(o)


def create_app(config_class=Config):
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')
    app.config.from_object(config_class)
    app.json_provider_class = _JSONProvider
    app.json = _JSONProvider(app)

    # Ensure data directories exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config.get('BACKUP_DIR', 'data/backups'), exist_ok=True)

    # Initialize extensions
    db.init_app(app)

    # Create tables and seed
    with app.app_context():
        from app import models  # noqa: ensure models registered
        db.create_all()
        from app.seed import seed_if_empty
        seed_if_empty()

    # Register blueprints
    from app.import_engine import bp as import_bp
    from app.parser import bp as parser_bp
    from app.revenue import bp as revenue_bp
    from app.infra import bp as infra_bp

    app.register_blueprint(import_bp, url_prefix='/api')
    app.register_blueprint(parser_bp, url_prefix='/api')
    app.register_blueprint(revenue_bp, url_prefix='/api')
    app.register_blueprint(infra_bp, url_prefix='/api')

    @app.route('/health')
    def health():
        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
        db_path = db_uri.replace('sqlite:///', '')
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        from app.models import BillingRecord
        count = BillingRecord.query.count()
        return jsonify({
            'status': 'healthy',
            'db_size_bytes': db_size,
            'record_count': count,
            'uptime_seconds': round(time.time() - _start_time, 1),
        })

    return app
