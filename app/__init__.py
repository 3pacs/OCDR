import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__, instance_relative_config=True)

    os.makedirs(app.instance_path, exist_ok=True)

    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", os.urandom(32).hex()
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(app.instance_path, 'ocdr.db')}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB max upload

    upload_base = os.path.join(app.static_folder, "uploads")
    app.config["UPLOAD_FOLDER_DOCS"] = os.path.join(upload_base, "documents")
    app.config["UPLOAD_FOLDER_PHOTOS"] = os.path.join(upload_base, "photos")
    os.makedirs(app.config["UPLOAD_FOLDER_DOCS"], exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER_PHOTOS"], exist_ok=True)

    app.config["OLLAMA_BASE_URL"] = os.environ.get(
        "OLLAMA_BASE_URL", "http://localhost:11434"
    )
    app.config["OLLAMA_MODEL"] = os.environ.get(
        "OLLAMA_MODEL", "hermes3"
    )

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "main.index"

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.routes import main_bp
    from app.api import api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    with app.app_context():
        db.create_all()

    return app
