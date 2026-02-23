from datetime import datetime, timezone
from app.extensions import db


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)
    sku = db.Column(db.String(100))
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    unit = db.Column(db.String(50))       # e.g. "box", "each", "case"
    unit_price = db.Column(db.Numeric(10, 2))
    category = db.Column(db.String(100))  # e.g. "X-Ray Supplies", "Medications"
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    vendor = db.relationship("Vendor", back_populates="products")
    purchase_items = db.relationship("PurchaseItem", back_populates="product", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "vendor_id": self.vendor_id,
            "sku": self.sku,
            "name": self.name,
            "description": self.description,
            "unit": self.unit,
            "unit_price": float(self.unit_price) if self.unit_price is not None else None,
            "category": self.category,
            "active": self.active,
        }

    def __repr__(self):
        return f"<Product {self.sku} - {self.name}>"
