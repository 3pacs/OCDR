"""Unit tests for SQLAlchemy models."""
import pytest
from app.models.vendor import Vendor
from app.models.product import Product
from app.models.purchase import Purchase, PurchaseItem
from app.models.document import Document


class TestVendorModel:
    def test_create_vendor(self, db_session):
        v = Vendor(name="TestVendor", slug="testvendor")
        db_session.add(v)
        db_session.flush()
        assert v.id is not None
        assert v.active is True

    def test_vendor_to_dict(self, vendor_spectrumxray):
        d = vendor_spectrumxray.to_dict()
        assert d["name"] == "SpectrumXray"
        assert d["slug"] == "spectrumxray"
        assert d["active"] is True

    def test_vendor_repr(self, vendor_spectrumxray):
        assert "SpectrumXray" in repr(vendor_spectrumxray)

    def test_vendor_slug_unique(self, db_session, vendor_spectrumxray):
        duplicate = Vendor(name="Another", slug="spectrumxray")
        db_session.add(duplicate)
        with pytest.raises(Exception):
            db_session.flush()

    def test_vendor_defaults(self, db_session):
        v = Vendor(name="MinVendor", slug="minvendor")
        db_session.add(v)
        db_session.flush()
        assert v.active is True
        assert v.created_at is not None


class TestProductModel:
    def test_create_product(self, db_session, vendor_spectrumxray):
        p = Product(
            vendor_id=vendor_spectrumxray.id,
            name="X-Ray Film",
            sku="XF-001",
            unit_price=25.00,
        )
        db_session.add(p)
        db_session.flush()
        assert p.id is not None

    def test_product_to_dict(self, db_session, vendor_spectrumxray):
        p = Product(vendor_id=vendor_spectrumxray.id, name="Film", sku="F1", unit_price=10.0)
        db_session.add(p)
        db_session.flush()
        d = p.to_dict()
        assert d["sku"] == "F1"
        assert d["unit_price"] == 10.0

    def test_product_relationship(self, db_session, vendor_spectrumxray):
        p = Product(vendor_id=vendor_spectrumxray.id, name="Film", sku="F2")
        db_session.add(p)
        db_session.flush()
        assert p.vendor.name == "SpectrumXray"


class TestPurchaseModel:
    def test_create_purchase(self, db_session, vendor_spectrumxray):
        p = Purchase(
            vendor_id=vendor_spectrumxray.id,
            order_number="ORD-999",
            status="pending",
            total=50.00,
        )
        db_session.add(p)
        db_session.flush()
        assert p.id is not None
        assert p.status == "pending"

    def test_purchase_to_dict(self, purchase_for_spectrumxray):
        d = purchase_for_spectrumxray.to_dict()
        assert d["order_number"] == "ORD-001"
        assert d["total"] == 110.0
        assert len(d["items"]) == 1

    def test_purchase_items_cascade_delete(self, db_session, vendor_spectrumxray):
        from app.extensions import db
        p = Purchase(vendor_id=vendor_spectrumxray.id, order_number="ORD-DEL", status="pending")
        db_session.add(p)
        db_session.flush()
        item = PurchaseItem(purchase_id=p.id, description="Widget", quantity=1,
                            unit_price=5.0, line_total=5.0)
        db_session.add(item)
        db_session.flush()
        item_id = item.id
        db_session.delete(p)
        db_session.flush()
        result = db_session.get(PurchaseItem, item_id)
        assert result is None

    def test_purchase_item_to_dict(self, purchase_for_spectrumxray):
        item = purchase_for_spectrumxray.items[0]
        d = item.to_dict()
        assert d["sku"] == "XR-100"
        assert d["quantity"] == 2.0
        assert d["line_total"] == 50.0


class TestDocumentModel:
    def test_create_document(self, db_session):
        doc = Document(
            filename="abc123.csv",
            original_filename="order.csv",
            file_type="csv",
            file_size=1024,
            category="invoice",
        )
        db_session.add(doc)
        db_session.flush()
        assert doc.id is not None
        assert doc.parsed is False

    def test_document_to_dict(self, db_session):
        doc = Document(filename="x.pdf", original_filename="invoice.pdf",
                       file_type="pdf", file_size=2048, category="invoice")
        db_session.add(doc)
        db_session.flush()
        d = doc.to_dict()
        assert d["file_type"] == "pdf"
        assert d["parsed"] is False
