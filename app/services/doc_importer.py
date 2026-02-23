"""
Document import service.

Handles uploading and basic parsing of:
  - PDF  (text extraction via PyPDF2)
  - CSV  (delegates to csv_importer)
  - XLSX (delegates to csv_importer)
  - Generic files (store without parsing)
"""
from __future__ import annotations

import os
import uuid
from typing import Any
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage

ALLOWED_EXTENSIONS = {"csv", "pdf", "xlsx", "xls", "docx", "txt"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file: FileStorage, upload_folder: str) -> dict[str, Any]:
    """
    Save an uploaded file to disk with a unique name.
    Returns metadata dict.
    """
    if not file or not file.filename:
        return {"success": False, "error": "No file provided"}

    if not allowed_file(file.filename):
        return {"success": False, "error": f"File type not allowed: {file.filename}"}

    original_name = secure_filename(file.filename)
    ext = original_name.rsplit(".", 1)[-1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    save_path = os.path.join(upload_folder, unique_name)

    file.save(save_path)
    size = os.path.getsize(save_path)

    return {
        "success": True,
        "filename": unique_name,
        "original_filename": original_name,
        "file_type": ext,
        "file_path": save_path,
        "file_size": size,
    }


def extract_pdf_text(filepath: str) -> dict[str, Any]:
    """Extract all text from a PDF file."""
    try:
        import PyPDF2

        pages = []
        with open(filepath, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                pages.append({"page": i + 1, "text": text})

        full_text = "\n".join(p["text"] for p in pages)
        return {
            "success": True,
            "pages": pages,
            "full_text": full_text,
            "page_count": len(pages),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "pages": [], "full_text": ""}


def parse_document(filepath: str, vendor_slug: str | None = None) -> dict[str, Any]:
    """
    Detect file type and run the appropriate parser.
    Optionally uses a vendor handler for vendor-specific invoices.
    """
    ext = filepath.rsplit(".", 1)[-1].lower()

    if ext == "csv":
        from app.services.csv_importer import import_vendor_csv, import_generic_csv
        if vendor_slug:
            return import_vendor_csv(filepath, vendor_slug)
        return import_generic_csv(filepath)

    if ext in ("xlsx", "xls"):
        from app.services.csv_importer import import_xlsx
        return import_xlsx(filepath)

    if ext == "pdf":
        if vendor_slug:
            from app.vendors.registry import VendorRegistry
            handler = VendorRegistry.get(vendor_slug)
            if handler:
                try:
                    result = handler.parse_invoice(filepath)
                    result["success"] = "error" not in result
                    return result
                except Exception as exc:
                    return {"success": False, "error": str(exc)}
        return extract_pdf_text(filepath)

    # Unsupported type — just flag as stored
    return {"success": True, "parsed": False, "note": f"File type '{ext}' stored but not parsed"}
