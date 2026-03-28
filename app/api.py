"""
API routes for document scanning, parsing, patient matching, and file management.
"""

import json
import os
import uuid
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from app import db
from app.models import Patient, Document, encrypt_value
from app.llm_parser import parse_document, match_patient

api_bp = Blueprint("api", __name__)

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp"}


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Document Upload & Scan
# ---------------------------------------------------------------------------

@api_bp.route("/documents/upload", methods=["POST"])
def upload_document():
    """Upload a document (image or PDF) for scanning and parsing."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not _allowed_file(file.filename):
        return jsonify({"error": f"File type not allowed. Accepted: {', '.join(ALLOWED_EXTENSIONS)}"}), 400

    # Save file with unique name
    ext = file.filename.rsplit(".", 1)[1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    save_path = os.path.join(current_app.config["UPLOAD_FOLDER_DOCS"], unique_name)
    file.save(save_path)

    file_size = os.path.getsize(save_path)
    file_type = "pdf" if ext == "pdf" else "image"

    # Create document record
    doc = Document(
        filename=unique_name,
        original_filename=secure_filename(file.filename),
        file_type=file_type,
        file_size=file_size,
        status="uploaded",
    )
    db.session.add(doc)
    db.session.commit()

    return jsonify({"document": doc.to_dict()}), 201


@api_bp.route("/documents/<int:doc_id>/parse", methods=["POST"])
def parse_doc(doc_id):
    """Run OCR + LLM parsing on an uploaded document."""
    doc = db.session.get(Document, doc_id)
    if not doc:
        return jsonify({"error": "Document not found"}), 404

    file_path = os.path.join(current_app.config["UPLOAD_FOLDER_DOCS"], doc.filename)
    if not os.path.exists(file_path):
        return jsonify({"error": "Document file missing from disk"}), 404

    doc.status = "processing"
    db.session.commit()

    try:
        result = parse_document(
            file_path,
            model=current_app.config["OLLAMA_MODEL"],
            base_url=current_app.config["OLLAMA_BASE_URL"],
        )

        doc.raw_ocr_text = result.get("raw_text", "")
        doc.extracted_data = json.dumps(result.get("parsed", {}))
        doc.llm_summary = result.get("parsed", {}).get("summary", "")

        parsed = result.get("parsed", {})
        doc.parsed_name = parsed.get("patient_name")
        doc.parsed_dob = parsed.get("date_of_birth")
        doc.parsed_address = parsed.get("address")
        doc.parsed_doc_type = parsed.get("document_type")
        doc.document_type = parsed.get("document_type")

        doc.status = "parsed"
        doc.processed_at = datetime.now(timezone.utc)

        if parsed.get("error"):
            doc.status = "error"
            doc.error_message = parsed["error"]

    except RuntimeError as e:
        doc.status = "error"
        doc.error_message = str(e)
    except Exception as e:
        doc.status = "error"
        doc.error_message = f"Parsing failed: {str(e)}"

    db.session.commit()
    return jsonify({"document": doc.to_dict()})


@api_bp.route("/documents/<int:doc_id>/match", methods=["POST"])
def match_doc(doc_id):
    """Match a parsed document to an existing patient using LLM."""
    doc = db.session.get(Document, doc_id)
    if not doc:
        return jsonify({"error": "Document not found"}), 404

    if not doc.extracted_data:
        return jsonify({"error": "Document has not been parsed yet"}), 400

    patients = Patient.query.all()
    if not patients:
        return jsonify({"error": "No patients in the system"}), 400

    patient_dicts = [p.to_dict() for p in patients]
    extracted = json.loads(doc.extracted_data) if doc.extracted_data else {}

    try:
        match_result = match_patient(
            extracted,
            patient_dicts,
            model=current_app.config["OLLAMA_MODEL"],
            base_url=current_app.config["OLLAMA_BASE_URL"],
        )

        matched_id = match_result.get("matched_patient_id")
        confidence = match_result.get("confidence", 0)

        if matched_id and confidence >= 0.5:
            doc.patient_id = matched_id
            doc.match_confidence = confidence
            doc.status = "matched"

            # Update patient info from document if it's an ID
            if doc.parsed_doc_type in ("drivers_license", "state_id"):
                patient = db.session.get(Patient, matched_id)
                if patient:
                    if doc.parsed_address and not patient.address:
                        patient.decrypted_address = doc.parsed_address
                    if doc.parsed_dob and not patient.date_of_birth:
                        from datetime import datetime as dt
                        try:
                            dob = dt.strptime(doc.parsed_dob, "%m/%d/%Y").date()
                            patient.date_of_birth = dob
                        except ValueError:
                            pass

            db.session.commit()
            return jsonify({
                "match": match_result,
                "document": doc.to_dict(),
            })
        else:
            doc.match_confidence = confidence
            return jsonify({
                "match": match_result,
                "message": "No confident match found. Assign manually.",
                "document": doc.to_dict(),
            })

    except Exception as e:
        return jsonify({"error": f"Matching failed: {str(e)}"}), 500


@api_bp.route("/documents/<int:doc_id>/assign", methods=["POST"])
def assign_document(doc_id):
    """Manually assign a document to a patient."""
    doc = db.session.get(Document, doc_id)
    if not doc:
        return jsonify({"error": "Document not found"}), 404

    data = request.get_json()
    patient_id = data.get("patient_id")
    if not patient_id:
        return jsonify({"error": "patient_id required"}), 400

    patient = db.session.get(Patient, patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    doc.patient_id = patient_id
    doc.status = "filed"

    # Update patient info from ID documents
    if doc.parsed_doc_type in ("drivers_license", "state_id"):
        if doc.parsed_address and not patient.address:
            patient.decrypted_address = doc.parsed_address
        if doc.parsed_dob and not patient.date_of_birth:
            try:
                from datetime import datetime as dt
                dob = dt.strptime(doc.parsed_dob, "%m/%d/%Y").date()
                patient.date_of_birth = dob
            except ValueError:
                pass

    db.session.commit()
    return jsonify({"document": doc.to_dict()})


@api_bp.route("/documents", methods=["GET"])
def list_documents():
    """List all documents, optionally filtered by status."""
    status = request.args.get("status")
    patient_id = request.args.get("patient_id")

    query = Document.query
    if status:
        query = query.filter_by(status=status)
    if patient_id:
        query = query.filter_by(patient_id=int(patient_id))

    docs = query.order_by(Document.created_at.desc()).all()
    return jsonify({"documents": [d.to_dict() for d in docs]})


@api_bp.route("/documents/<int:doc_id>", methods=["GET"])
def get_document(doc_id):
    """Get a single document's details."""
    doc = db.session.get(Document, doc_id)
    if not doc:
        return jsonify({"error": "Document not found"}), 404
    return jsonify({"document": doc.to_dict()})


@api_bp.route("/documents/<int:doc_id>", methods=["DELETE"])
def delete_document(doc_id):
    """Delete a document."""
    doc = db.session.get(Document, doc_id)
    if not doc:
        return jsonify({"error": "Document not found"}), 404

    file_path = os.path.join(current_app.config["UPLOAD_FOLDER_DOCS"], doc.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    db.session.delete(doc)
    db.session.commit()
    return jsonify({"message": "Document deleted"})


# ---------------------------------------------------------------------------
# Patient Management
# ---------------------------------------------------------------------------

@api_bp.route("/patients", methods=["GET"])
def list_patients():
    """List all patients."""
    search = request.args.get("search", "").strip()
    query = Patient.query

    if search:
        search_upper = f"%{search.upper()}%"
        query = query.filter(
            db.or_(
                Patient.last_name.ilike(search_upper),
                Patient.first_name.ilike(search_upper),
                Patient.patient_id_external.ilike(f"%{search}%"),
            )
        )

    patients = query.order_by(Patient.last_name, Patient.first_name).all()
    return jsonify({"patients": [p.to_dict() for p in patients]})


@api_bp.route("/patients/<int:patient_id>", methods=["GET"])
def get_patient(patient_id):
    """Get patient details with their documents."""
    patient = db.session.get(Patient, patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    data = patient.to_dict()
    data["documents"] = [d.to_dict() for d in patient.documents.all()]
    return jsonify({"patient": data})


@api_bp.route("/patients", methods=["POST"])
def create_patient():
    """Create a new patient."""
    data = request.get_json()

    if not data.get("first_name") or not data.get("last_name"):
        return jsonify({"error": "first_name and last_name required"}), 400

    patient = Patient(
        first_name=data["first_name"].strip().upper(),
        last_name=data["last_name"].strip().upper(),
        insurance_carrier=data.get("insurance_carrier", "").strip().upper() or None,
        patient_id_external=data.get("patient_id_external"),
        notes=data.get("notes"),
    )

    if data.get("date_of_birth"):
        try:
            patient.date_of_birth = datetime.strptime(
                data["date_of_birth"], "%Y-%m-%d"
            ).date()
        except ValueError:
            return jsonify({"error": "date_of_birth must be YYYY-MM-DD"}), 400

    if data.get("address"):
        patient.decrypted_address = data["address"]
    if data.get("phone"):
        patient.decrypted_phone = data["phone"]

    db.session.add(patient)
    db.session.commit()
    return jsonify({"patient": patient.to_dict()}), 201


@api_bp.route("/patients/<int:patient_id>", methods=["PUT"])
def update_patient(patient_id):
    """Update patient details."""
    patient = db.session.get(Patient, patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    data = request.get_json()

    if "first_name" in data:
        patient.first_name = data["first_name"].strip().upper()
    if "last_name" in data:
        patient.last_name = data["last_name"].strip().upper()
    if "date_of_birth" in data:
        try:
            patient.date_of_birth = datetime.strptime(
                data["date_of_birth"], "%Y-%m-%d"
            ).date()
        except (ValueError, TypeError):
            pass
    if "address" in data:
        patient.decrypted_address = data["address"]
    if "phone" in data:
        patient.decrypted_phone = data["phone"]
    if "insurance_carrier" in data:
        patient.insurance_carrier = data["insurance_carrier"].strip().upper() or None
    if "notes" in data:
        patient.notes = data["notes"]

    db.session.commit()
    return jsonify({"patient": patient.to_dict()})


@api_bp.route("/patients/<int:patient_id>/photo", methods=["POST"])
def upload_patient_photo(patient_id):
    """Upload a photo for a patient."""
    patient = db.session.get(Patient, patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    if "photo" not in request.files:
        return jsonify({"error": "No photo provided"}), 400

    photo = request.files["photo"]
    ext = photo.filename.rsplit(".", 1)[1].lower() if "." in photo.filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp"):
        return jsonify({"error": "Photo must be jpg, png, or webp"}), 400

    photo_name = f"patient_{patient_id}_{uuid.uuid4().hex[:8]}.{ext}"
    save_path = os.path.join(current_app.config["UPLOAD_FOLDER_PHOTOS"], photo_name)
    photo.save(save_path)

    # Remove old photo if exists
    if patient.photo_filename:
        old_path = os.path.join(current_app.config["UPLOAD_FOLDER_PHOTOS"], patient.photo_filename)
        if os.path.exists(old_path):
            os.remove(old_path)

    patient.photo_filename = photo_name
    db.session.commit()

    return jsonify({"patient": patient.to_dict()})


# ---------------------------------------------------------------------------
# Pipeline: Upload → Parse → Match in one shot
# ---------------------------------------------------------------------------

@api_bp.route("/scan", methods=["POST"])
def scan_and_process():
    """
    Full pipeline: upload a document, OCR + LLM parse, and attempt patient match.
    This is the main endpoint for the scanner workflow.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "" or not _allowed_file(file.filename):
        return jsonify({"error": "Invalid file"}), 400

    # 1. Save file
    ext = file.filename.rsplit(".", 1)[1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    save_path = os.path.join(current_app.config["UPLOAD_FOLDER_DOCS"], unique_name)
    file.save(save_path)

    doc = Document(
        filename=unique_name,
        original_filename=secure_filename(file.filename),
        file_type="pdf" if ext == "pdf" else "image",
        file_size=os.path.getsize(save_path),
        status="processing",
    )
    db.session.add(doc)
    db.session.commit()

    # 2. Parse
    try:
        result = parse_document(
            save_path,
            model=current_app.config["OLLAMA_MODEL"],
            base_url=current_app.config["OLLAMA_BASE_URL"],
        )

        doc.raw_ocr_text = result.get("raw_text", "")
        doc.extracted_data = json.dumps(result.get("parsed", {}))
        parsed = result.get("parsed", {})
        doc.llm_summary = parsed.get("summary", "")
        doc.parsed_name = parsed.get("patient_name")
        doc.parsed_dob = parsed.get("date_of_birth")
        doc.parsed_address = parsed.get("address")
        doc.parsed_doc_type = parsed.get("document_type")
        doc.document_type = parsed.get("document_type")
        doc.status = "parsed"
        doc.processed_at = datetime.now(timezone.utc)

    except Exception as e:
        doc.status = "error"
        doc.error_message = str(e)
        db.session.commit()
        return jsonify({"document": doc.to_dict(), "match": None}), 200

    # 3. Auto-match
    match_result = None
    patients = Patient.query.all()
    if patients and doc.parsed_name:
        try:
            patient_dicts = [p.to_dict() for p in patients]
            extracted = json.loads(doc.extracted_data) if doc.extracted_data else {}
            match_result = match_patient(
                extracted, patient_dicts,
                model=current_app.config["OLLAMA_MODEL"],
                base_url=current_app.config["OLLAMA_BASE_URL"],
            )
            matched_id = match_result.get("matched_patient_id")
            confidence = match_result.get("confidence", 0)
            doc.match_confidence = confidence

            if matched_id and confidence >= 0.7:
                doc.patient_id = matched_id
                doc.status = "matched"

                # Auto-update patient from ID
                if doc.parsed_doc_type in ("drivers_license", "state_id"):
                    patient = db.session.get(Patient, matched_id)
                    if patient:
                        if doc.parsed_address and not patient.address:
                            patient.decrypted_address = doc.parsed_address
                        if doc.parsed_dob and not patient.date_of_birth:
                            try:
                                dob = datetime.strptime(doc.parsed_dob, "%m/%d/%Y").date()
                                patient.date_of_birth = dob
                            except ValueError:
                                pass

        except Exception as e:
            match_result = {"error": str(e)}

    db.session.commit()
    return jsonify({"document": doc.to_dict(), "match": match_result})


# ---------------------------------------------------------------------------
# Ollama status
# ---------------------------------------------------------------------------

@api_bp.route("/ollama/status", methods=["GET"])
def ollama_status():
    """Check if Ollama is running and which models are available."""
    import requests as req
    base_url = current_app.config["OLLAMA_BASE_URL"]
    try:
        resp = req.get(f"{base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        return jsonify({
            "status": "connected",
            "base_url": base_url,
            "configured_model": current_app.config["OLLAMA_MODEL"],
            "available_models": models,
        })
    except Exception:
        return jsonify({
            "status": "disconnected",
            "base_url": base_url,
            "error": "Cannot connect to Ollama. Run: ollama serve",
        }), 503
