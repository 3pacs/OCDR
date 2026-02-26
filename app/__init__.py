import os
import time
from flask import Flask, jsonify
from app.config import Config
from app.models import db


_start_time = time.time()


def create_app(config_class=Config):
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates'),
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'),
    )
    app.config.from_object(config_class)

    db.init_app(app)

    # Register blueprints
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
