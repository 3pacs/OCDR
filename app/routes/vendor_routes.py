from flask import Blueprint, jsonify, request
from app.extensions import db
from app.models.vendor import Vendor
from app.models.purchase import Purchase, PurchaseItem
from app.models.product import Product

vendors_bp = Blueprint("vendors", __name__)


# ------------------------------------------------------------------ #
# Vendors                                                             #
# ------------------------------------------------------------------ #

@vendors_bp.get("/")
def list_vendors():
    vendors = db.session.execute(db.select(Vendor).order_by(Vendor.name)).scalars().all()
    return jsonify([v.to_dict() for v in vendors])


@vendors_bp.get("/<int:vendor_id>")
def get_vendor(vendor_id: int):
    vendor = db.get_or_404(Vendor, vendor_id)
    return jsonify(vendor.to_dict())


@vendors_bp.post("/")
def create_vendor():
    data = request.get_json(force=True)
    if not data.get("name") or not data.get("slug"):
        return jsonify({"error": "name and slug are required"}), 400

    exists = db.session.execute(
        db.select(Vendor).where(Vendor.slug == data["slug"])
    ).scalar_one_or_none()
    if exists:
        return jsonify({"error": "slug already exists"}), 409

    vendor = Vendor(
        name=data["name"],
        slug=data["slug"],
        contact_name=data.get("contact_name"),
        contact_email=data.get("contact_email"),
        contact_phone=data.get("contact_phone"),
        website=data.get("website"),
        account_number=data.get("account_number"),
        notes=data.get("notes"),
    )
    db.session.add(vendor)
    db.session.commit()
    return jsonify(vendor.to_dict()), 201


@vendors_bp.put("/<int:vendor_id>")
def update_vendor(vendor_id: int):
    vendor = db.get_or_404(Vendor, vendor_id)
    data = request.get_json(force=True)
    for field in ("name", "contact_name", "contact_email", "contact_phone",
                  "website", "account_number", "notes", "active"):
        if field in data:
            setattr(vendor, field, data[field])
    db.session.commit()
    return jsonify(vendor.to_dict())


@vendors_bp.delete("/<int:vendor_id>")
def delete_vendor(vendor_id: int):
    vendor = db.get_or_404(Vendor, vendor_id)
    vendor.active = False
    db.session.commit()
    return jsonify({"message": "Vendor deactivated", "id": vendor_id})


# ------------------------------------------------------------------ #
# Purchases                                                           #
# ------------------------------------------------------------------ #

@vendors_bp.get("/<int:vendor_id>/purchases")
def list_purchases(vendor_id: int):
    db.get_or_404(Vendor, vendor_id)
    purchases = db.session.execute(
        db.select(Purchase)
        .where(Purchase.vendor_id == vendor_id)
        .order_by(Purchase.created_at.desc())
    ).scalars().all()
    return jsonify([p.to_dict() for p in purchases])


@vendors_bp.post("/<int:vendor_id>/purchases")
def create_purchase(vendor_id: int):
    db.get_or_404(Vendor, vendor_id)
    data = request.get_json(force=True)

    from datetime import date

    def _parse_date(val):
        if not val:
            return None
        try:
            return date.fromisoformat(str(val))
        except ValueError:
            return None

    purchase = Purchase(
        vendor_id=vendor_id,
        order_number=data.get("order_number"),
        invoice_number=data.get("invoice_number"),
        order_date=_parse_date(data.get("order_date")),
        received_date=_parse_date(data.get("received_date")),
        status=data.get("status", "pending"),
        subtotal=data.get("subtotal", 0),
        tax=data.get("tax", 0),
        shipping=data.get("shipping", 0),
        total=data.get("total", 0),
        notes=data.get("notes"),
        source=data.get("source", "manual"),
    )
    db.session.add(purchase)
    db.session.flush()

    for item_data in data.get("items", []):
        item = PurchaseItem(
            purchase_id=purchase.id,
            sku=item_data.get("sku"),
            description=item_data.get("description"),
            quantity=item_data.get("quantity", 1),
            unit_price=item_data.get("unit_price", 0),
            line_total=item_data.get("line_total", 0),
        )
        db.session.add(item)

    db.session.commit()
    return jsonify(purchase.to_dict()), 201


@vendors_bp.get("/<int:vendor_id>/purchases/<int:purchase_id>")
def get_purchase(vendor_id: int, purchase_id: int):
    purchase = db.session.execute(
        db.select(Purchase)
        .where(Purchase.id == purchase_id, Purchase.vendor_id == vendor_id)
    ).scalar_one_or_404()
    return jsonify(purchase.to_dict())


@vendors_bp.put("/<int:vendor_id>/purchases/<int:purchase_id>")
def update_purchase(vendor_id: int, purchase_id: int):
    purchase = db.session.execute(
        db.select(Purchase)
        .where(Purchase.id == purchase_id, Purchase.vendor_id == vendor_id)
    ).scalar_one_or_404()
    data = request.get_json(force=True)
    for field in ("order_number", "invoice_number", "status", "subtotal",
                  "tax", "shipping", "total", "notes"):
        if field in data:
            setattr(purchase, field, data[field])
    db.session.commit()
    return jsonify(purchase.to_dict())


# ------------------------------------------------------------------ #
# Products                                                            #
# ------------------------------------------------------------------ #

@vendors_bp.get("/<int:vendor_id>/products")
def list_products(vendor_id: int):
    db.get_or_404(Vendor, vendor_id)
    products = db.session.execute(
        db.select(Product).where(Product.vendor_id == vendor_id).order_by(Product.name)
    ).scalars().all()
    return jsonify([p.to_dict() for p in products])


@vendors_bp.post("/<int:vendor_id>/products")
def create_product(vendor_id: int):
    db.get_or_404(Vendor, vendor_id)
    data = request.get_json(force=True)
    if not data.get("name"):
        return jsonify({"error": "name is required"}), 400
    product = Product(
        vendor_id=vendor_id,
        sku=data.get("sku"),
        name=data["name"],
        description=data.get("description"),
        unit=data.get("unit"),
        unit_price=data.get("unit_price"),
        category=data.get("category"),
    )
    db.session.add(product)
    db.session.commit()
    return jsonify(product.to_dict()), 201
