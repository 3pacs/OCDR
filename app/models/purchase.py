from datetime import datetime, timezone
from app.extensions import db


class Purchase(db.Model):
    __tablename__ = "purchases"

    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)
    order_number = db.Column(db.String(100))
    invoice_number = db.Column(db.String(100))
    order_date = db.Column(db.Date)
    received_date = db.Column(db.Date)
    status = db.Column(
        db.String(30), default="pending"
    )  # pending, ordered, received, cancelled
    subtotal = db.Column(db.Numeric(10, 2), default=0)
    tax = db.Column(db.Numeric(10, 2), default=0)
    shipping = db.Column(db.Numeric(10, 2), default=0)
    total = db.Column(db.Numeric(10, 2), default=0)
    notes = db.Column(db.Text)
    source = db.Column(db.String(50), default="manual")  # manual, csv_import, api
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    vendor = db.relationship("Vendor", back_populates="purchases")
    items = db.relationship(
        "PurchaseItem", back_populates="purchase", cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "vendor_id": self.vendor_id,
            "order_number": self.order_number,
            "invoice_number": self.invoice_number,
            "order_date": self.order_date.isoformat() if self.order_date else None,
            "received_date": self.received_date.isoformat() if self.received_date else None,
            "status": self.status,
            "subtotal": float(self.subtotal) if self.subtotal is not None else 0,
            "tax": float(self.tax) if self.tax is not None else 0,
            "shipping": float(self.shipping) if self.shipping is not None else 0,
            "total": float(self.total) if self.total is not None else 0,
            "notes": self.notes,
            "source": self.source,
            "items": [item.to_dict() for item in self.items],
        }

    def __repr__(self):
        return f"<Purchase #{self.order_number} from vendor {self.vendor_id}>"


class PurchaseItem(db.Model):
    __tablename__ = "purchase_items"

    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchases.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)
    sku = db.Column(db.String(100))
    description = db.Column(db.String(255))
    quantity = db.Column(db.Numeric(10, 3), default=1)
    unit_price = db.Column(db.Numeric(10, 2), default=0)
    line_total = db.Column(db.Numeric(10, 2), default=0)

    purchase = db.relationship("Purchase", back_populates="items")
    product = db.relationship("Product", back_populates="purchase_items")

    def to_dict(self):
        return {
            "id": self.id,
            "purchase_id": self.purchase_id,
            "product_id": self.product_id,
            "sku": self.sku,
            "description": self.description,
            "quantity": float(self.quantity) if self.quantity is not None else 0,
            "unit_price": float(self.unit_price) if self.unit_price is not None else 0,
            "line_total": float(self.line_total) if self.line_total is not None else 0,
        }
