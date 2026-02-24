import os
from flask import Flask
from app.extensions import db
from app.config import config_map


def create_app(env: str | None = None) -> Flask:
    if env is None:
        env = os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config_map.get(env, config_map["development"]))

    # Ensure upload folder exists
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Init extensions
    db.init_app(app)

    # Register blueprints
    from app.routes.vendor_routes import vendors_bp
    from app.routes.import_routes import imports_bp
    from app.routes.main_routes import main_bp
    from app.routes.connector_routes import connectors_bp
    from app.routes.reconciliation_routes import recon_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(vendors_bp, url_prefix="/api/vendors")
    app.register_blueprint(imports_bp, url_prefix="/api/imports")
    app.register_blueprint(connectors_bp, url_prefix="/api/connectors")
    app.register_blueprint(recon_bp, url_prefix="/api/reconciliation")

    # Create tables
    with app.app_context():
        db.create_all()
        _seed_default_vendors(app)

    return app


def _seed_default_vendors(app: Flask) -> None:
    """Insert SpectrumXray and PetNet if they don't exist yet."""
    from app.models.vendor import Vendor

    defaults = [
        {
            "name": "SpectrumXray",
            "slug": "spectrumxray",
            "website": "https://www.spectrumxray.com",
            "notes": "X-ray supplies and imaging equipment",
        },
        {
            "name": "PetNet",
            "slug": "petnet",
            "website": "https://www.petnet.com",
            "notes": "Veterinary supplies and medications",
        },
    ]

    for data in defaults:
        exists = db.session.execute(
            db.select(Vendor).where(Vendor.slug == data["slug"])
        ).scalar_one_or_none()
        if not exists:
            db.session.add(Vendor(**data))

    db.session.commit()
