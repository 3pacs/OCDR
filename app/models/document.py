from datetime import datetime, timezone
from app.extensions import db


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchases.id"), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255))
    file_type = db.Column(db.String(30))   # csv, pdf, xlsx, docx, etc.
    file_size = db.Column(db.Integer)       # bytes
    file_path = db.Column(db.String(500))
    category = db.Column(db.String(100))   # invoice, order, catalog, report, other
    notes = db.Column(db.Text)
    parsed = db.Column(db.Boolean, default=False)
    parse_error = db.Column(db.Text)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    vendor = db.relationship("Vendor", backref="documents")
    purchase = db.relationship("Purchase", backref="documents")

    def to_dict(self):
        return {
            "id": self.id,
            "vendor_id": self.vendor_id,
            "purchase_id": self.purchase_id,
            "filename": self.filename,
            "original_filename": self.original_filename,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "category": self.category,
            "notes": self.notes,
            "parsed": self.parsed,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
        }

    def __repr__(self):
        return f"<Document {self.original_filename}>"
