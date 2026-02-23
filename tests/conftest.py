"""
pytest configuration and shared fixtures for OCDR test suite.
"""
import os
import csv
import tempfile
import pytest

from app import create_app
from app.extensions import db as _db
from app.models.vendor import Vendor
from app.models.product import Product
from app.models.purchase import Purchase, PurchaseItem
from app.models.document import Document


# ------------------------------------------------------------------ #
# App / DB fixtures                                                   #
# ------------------------------------------------------------------ #

@pytest.fixture(scope="session")
def app():
    """Create a Flask app configured for testing (in-memory SQLite)."""
    flask_app = create_app("testing")
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        UPLOAD_FOLDER=tempfile.mkdtemp(),
    )
    yield flask_app


@pytest.fixture(scope="session")
def db(app):
    """Create tables once per session."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.drop_all()


@pytest.fixture(autouse=True)
def db_session(db, app):
    """
    Wrap each test in a transaction that is rolled back afterwards,
    so tests remain isolated without recreating tables.
    """
    with app.app_context():
        connection = db.engine.connect()
        transaction = connection.begin()
        db.session.bind = connection  # type: ignore[attr-defined]
        yield db.session
        db.session.remove()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(app):
    return app.test_client()


# ------------------------------------------------------------------ #
# Model fixtures                                                      #
# ------------------------------------------------------------------ #

@pytest.fixture
def vendor_spectrumxray(db_session):
    v = Vendor(name="SpectrumXray", slug="spectrumxray",
               website="https://spectrumxray.com", active=True)
    db_session.add(v)
    db_session.flush()
    return v


@pytest.fixture
def vendor_petnet(db_session):
    v = Vendor(name="PetNet", slug="petnet",
               website="https://petnet.com", active=True)
    db_session.add(v)
    db_session.flush()
    return v


@pytest.fixture
def purchase_for_spectrumxray(db_session, vendor_spectrumxray):
    p = Purchase(
        vendor_id=vendor_spectrumxray.id,
        order_number="ORD-001",
        status="received",
        subtotal=100.00,
        total=110.00,
        tax=10.00,
        source="manual",
    )
    db_session.add(p)
    db_session.flush()
    item = PurchaseItem(
        purchase_id=p.id,
        sku="XR-100",
        description="X-Ray Film 8x10",
        quantity=2,
        unit_price=25.00,
        line_total=50.00,
    )
    db_session.add(item)
    db_session.flush()
    return p


# ------------------------------------------------------------------ #
# File fixtures                                                       #
# ------------------------------------------------------------------ #

@pytest.fixture
def sample_csv_path(tmp_path):
    """Create a minimal vendor-style CSV file."""
    f = tmp_path / "order.csv"
    with open(f, "w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["Item #", "Description", "Qty", "Unit Price", "Total"])
        writer.writeheader()
        writer.writerow({"Item #": "XR-100", "Description": "X-Ray Film 8x10",
                         "Qty": "2", "Unit Price": "25.00", "Total": "50.00"})
        writer.writerow({"Item #": "XR-200", "Description": "Developer Solution",
                         "Qty": "1", "Unit Price": "40.00", "Total": "40.00"})
    return str(f)


@pytest.fixture
def sample_petnet_csv_path(tmp_path):
    """Create a minimal PetNet-style CSV file."""
    f = tmp_path / "petnet_order.csv"
    with open(f, "w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["Catalog #", "Description", "Qty", "Unit Price", "Amount"])
        writer.writeheader()
        writer.writerow({"Catalog #": "PN-500", "Description": "Amoxicillin 250mg",
                         "Qty": "10", "Unit Price": "5.00", "Amount": "50.00"})
    return str(f)
