from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def create_app(config_class=None):
    app = Flask(
        __name__,
        template_folder='../templates',
        static_folder='../static',
        instance_relative_config=True,
    )

    if config_class:
        app.config.from_object(config_class)
    else:
        from app.config import Config
        app.config.from_object(Config)

    db.init_app(app)

    # Register blueprints
    from app.ui.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)

    from app.ui.chatbot import chatbot_bp
    app.register_blueprint(chatbot_bp, url_prefix='/chatbot')

    from app.ui.calendar import calendar_bp
    app.register_blueprint(calendar_bp)

    # Create tables
    with app.app_context():
        from app import models  # noqa: F401
        db.create_all()

    return app
