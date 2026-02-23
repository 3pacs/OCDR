from flask import Blueprint, jsonify, request, current_app
from app.extensions import db
from app.models.document import Document
from app.models.purchase import Purchase, PurchaseItem
from app.services.doc_importer import save_upload, parse_document
from app.services.csv_importer import preview_csv

imports_bp = Blueprint("imports", __name__)


@imports_bp.post("/upload")
def upload_document():
    """
    Upload a file and store its metadata in the documents table.
    Form fields:
      file       - the uploaded file (required)
      vendor_id  - int (optional)
      purchase_id- int (optional)
      category   - string (optional)
      notes      - string (optional)
      auto_parse - "true"/"false" (default true)
    """
    if "file" not in request.files:
        return jsonify({"error": "No file part in request"}), 400

    file = request.files["file"]
    vendor_id = request.form.get("vendor_id", type=int)
    purchase_id = request.form.get("purchase_id", type=int)
    category = request.form.get("category", "other")
    notes = request.form.get("notes", "")
    auto_parse = request.form.get("auto_parse", "true").lower() == "true"

    save_result = save_upload(file, current_app.config["UPLOAD_FOLDER"])
    if not save_result["success"]:
        return jsonify({"error": save_result["error"]}), 400

    doc = Document(
        vendor_id=vendor_id,
        purchase_id=purchase_id,
        filename=save_result["filename"],
        original_filename=save_result["original_filename"],
        file_type=save_result["file_type"],
        file_size=save_result["file_size"],
        file_path=save_result["file_path"],
        category=category,
        notes=notes,
        parsed=False,
    )
    db.session.add(doc)
    db.session.flush()

    parse_result: dict = {}
    if auto_parse and save_result["file_type"] in ("csv", "xlsx", "xls", "pdf"):
        vendor_slug = _get_vendor_slug(vendor_id)
        parse_result = parse_document(save_result["file_path"], vendor_slug)
        doc.parsed = parse_result.get("success", False)
        if not doc.parsed:
            doc.parse_error = parse_result.get("error", "Unknown parse error")

    db.session.commit()

    return jsonify({
        "document": doc.to_dict(),
        "parse_result": parse_result,
    }), 201


@imports_bp.post("/preview")
def preview_file():
    """
    Preview the first rows of an uploaded CSV without saving.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    import tempfile, os
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        file.save(tmp.name)
        result = preview_csv(tmp.name, rows=50)
        os.unlink(tmp.name)

    return jsonify(result)


@imports_bp.post("/import-purchase")
def import_purchase():
    """
    Convert parsed CSV items into a new Purchase record.
    JSON body:
      vendor_id   - int (required)
      items       - list of {sku, description, quantity, unit_price, line_total}
      order_number, invoice_number, order_date, status, notes (all optional)
    """
    data = request.get_json(force=True)
    vendor_id = data.get("vendor_id")
    if not vendor_id:
        return jsonify({"error": "vendor_id required"}), 400

    items = data.get("items", [])
    subtotal = sum(float(i.get("line_total", 0)) for i in items)

    purchase = Purchase(
        vendor_id=vendor_id,
        order_number=data.get("order_number"),
        invoice_number=data.get("invoice_number"),
        status=data.get("status", "received"),
        subtotal=subtotal,
        total=subtotal + float(data.get("tax", 0)) + float(data.get("shipping", 0)),
        tax=data.get("tax", 0),
        shipping=data.get("shipping", 0),
        notes=data.get("notes"),
        source="csv_import",
    )
    db.session.add(purchase)
    db.session.flush()

    for item_data in items:
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


@imports_bp.get("/documents")
def list_documents():
    docs = db.session.execute(
        db.select(Document).order_by(Document.uploaded_at.desc())
    ).scalars().all()
    return jsonify([d.to_dict() for d in docs])


# ------------------------------------------------------------------ #
# Internal helper                                                     #
# ------------------------------------------------------------------ #

def _get_vendor_slug(vendor_id: int | None) -> str | None:
    if not vendor_id:
        return None
    from app.models.vendor import Vendor
    vendor = db.session.get(Vendor, vendor_id)
    return vendor.slug if vendor else None
