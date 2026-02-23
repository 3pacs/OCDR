from datetime import datetime, timezone
from app.extensions import db


class Vendor(db.Model):
    __tablename__ = "vendors"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    slug = db.Column(db.String(60), nullable=False, unique=True)  # e.g. "spectrumxray"
    contact_name = db.Column(db.String(120))
    contact_email = db.Column(db.String(200))
    contact_phone = db.Column(db.String(30))
    website = db.Column(db.String(255))
    account_number = db.Column(db.String(100))
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    purchases = db.relationship("Purchase", back_populates="vendor", lazy="dynamic")
    products = db.relationship("Product", back_populates="vendor", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "website": self.website,
            "account_number": self.account_number,
            "notes": self.notes,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Vendor {self.name}>"
