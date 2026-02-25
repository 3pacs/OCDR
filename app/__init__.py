from flask import Flask
from app.config import Config
from app.models import db


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

    # Register blueprints
    from app.ui.dashboard import ui_bp
    from app.ui.api import api_bp

    app.register_blueprint(ui_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    with app.app_context():
        db.create_all()

    return app
