"""PDF Import Engine (F-12).

Extracts billing data from digital PDFs using pdfplumber.
Falls back to basic text extraction if pdfplumber unavailable.
Uses shared validation for normalization, dedup, and PSMA detection.
"""

import os
import re

from app.models import db, BillingRecord
from app.import_engine.validation import (
    parse_date, parse_float, parse_bool, normalize_modality,
    normalize_carrier, detect_psma, compute_total_payment,
    build_dedup_set, is_duplicate,
)


try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


def import_pdf(filepath):
    """Import billing data from a PDF file.

    Tries pdfplumber table extraction first.
    Falls back to text-based line parsing.

    Returns:
        dict: {imported, skipped, errors, total_rows, filename}
    """
    result = {
        "imported": 0,
        "skipped": 0,
        "errors": [],
        "total_rows": 0,
        "filename": os.path.basename(filepath),
        "method": "none",
    }

    if not os.path.exists(filepath):
        result["errors"].append("File not found")
        return result

    if HAS_PDFPLUMBER:
        return _import_with_pdfplumber(filepath, result)
    else:
        result["errors"].append(
            "pdfplumber not installed. Install with: pip install pdfplumber. "
            "PDF import requires this library for table extraction."
        )
        return result


def _import_with_pdfplumber(filepath, result):
    """Extract tables from PDF using pdfplumber."""
    result["method"] = "pdfplumber"

    try:
        with pdfplumber.open(filepath) as pdf:
            all_rows = []
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    all_rows.extend(table)

            if not all_rows:
                # Fall back to text extraction
                return _import_from_text(pdf, result)

            # Try to find header row
            headers = None
            data_start = 0
            for i, row in enumerate(all_rows):
                row_lower = [str(c).lower() if c else "" for c in row]
                if any("patient" in c for c in row_lower) or any("name" in c for c in row_lower):
                    headers = row_lower
                    data_start = i + 1
                    break

            if not headers:
                headers = [str(c).lower() if c else "" for c in all_rows[0]]
                data_start = 1

            # Map columns
            col_map = _detect_columns(headers)
            if not col_map:
                result["errors"].append(f"Cannot map PDF columns. Found: {headers}")
                return result

            existing = build_dedup_set()
            batch = []
            for row in all_rows[data_start:]:
                result["total_rows"] += 1
                try:
                    data = {}
                    for col_idx, field in col_map.items():
                        if col_idx < len(row) and row[col_idx]:
                            data[field] = row[col_idx]

                    patient = str(data.get("patient_name", "")).strip()
                    if not patient:
                        result["skipped"] += 1
                        continue

                    svc_date = parse_date(data.get("service_date"))
                    if not svc_date:
                        result["skipped"] += 1
                        continue

                    scan_type = str(data.get("scan_type", "")).strip() or "UNKNOWN"
                    modality = normalize_modality(data.get("modality"))

                    if is_duplicate(patient, svc_date, scan_type, modality, existing):
                        result["skipped"] += 1
                        continue

                    description = str(data.get("description", "")).strip() or None
                    primary = parse_float(data.get("primary_payment"))
                    secondary = parse_float(data.get("secondary_payment"))
                    total = parse_float(data.get("total_payment"))
                    total = compute_total_payment(primary, secondary, total)

                    rec = BillingRecord(
                        patient_name=patient,
                        referring_doctor=str(data.get("referring_doctor", "")).strip() or "UNKNOWN",
                        scan_type=scan_type,
                        gado_used=parse_bool(data.get("gado_used")),
                        modality=modality,
                        insurance_carrier=normalize_carrier(data.get("insurance_carrier")),
                        service_date=svc_date,
                        primary_payment=primary,
                        secondary_payment=secondary,
                        total_payment=total,
                        description=description,
                        is_psma=detect_psma(description, scan_type),
                        import_source="PDF_IMPORT",
                    )
                    batch.append(rec)
                except Exception as e:
                    result["errors"].append(f"Row: {e}")

            if batch:
                db.session.bulk_save_objects(batch)
                db.session.commit()
                result["imported"] = len(batch)

    except Exception as e:
        result["errors"].append(f"PDF parse error: {e}")

    return result


def _import_from_text(pdf, result):
    """Fallback: extract text and parse line-by-line."""
    result["method"] = "text_extraction"

    all_text = ""
    for page in pdf.pages:
        all_text += page.extract_text() or ""

    if not all_text.strip():
        result["errors"].append("No extractable text found in PDF")
        return result

    lines = all_text.strip().split("\n")
    result["total_rows"] = len(lines)

    # Look for date + name patterns
    date_pattern = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})")
    money_pattern = re.compile(r"\$?([\d,]+\.\d{2})")

    existing = build_dedup_set()
    batch = []
    for line in lines:
        dates = date_pattern.findall(line)
        amounts = money_pattern.findall(line)

        if dates and len(line) > 20:
            svc_date = parse_date(dates[0])
            if not svc_date:
                continue

            # Extract name (text before the first date)
            name_part = line[:line.index(dates[0])].strip()
            if len(name_part) < 3:
                continue

            if is_duplicate(name_part, svc_date, "UNKNOWN", "HMRI", existing):
                result["skipped"] += 1
                continue

            total = parse_float(amounts[-1]) if amounts else 0.0

            rec = BillingRecord(
                patient_name=name_part,
                referring_doctor="UNKNOWN",
                scan_type="UNKNOWN",
                modality="HMRI",
                insurance_carrier="UNKNOWN",
                service_date=svc_date,
                total_payment=total,
                import_source="PDF_IMPORT",
            )
            batch.append(rec)

    if batch:
        db.session.bulk_save_objects(batch)
        db.session.commit()
        result["imported"] = len(batch)

    return result


def _detect_columns(headers):
    """Map PDF table headers to model fields."""
    aliases = {
        "patient": "patient_name", "name": "patient_name", "patient name": "patient_name",
        "doctor": "referring_doctor", "referring": "referring_doctor",
        "scan": "scan_type", "procedure": "scan_type", "exam": "scan_type",
        "type": "modality", "modality": "modality",
        "date": "service_date", "dos": "service_date", "service date": "service_date",
        "total": "total_payment", "payment": "total_payment", "amount": "total_payment",
        "primary": "primary_payment",
        "secondary": "secondary_payment",
        "insurance": "insurance_carrier", "carrier": "insurance_carrier", "payer": "insurance_carrier",
        "gado": "gado_used", "contrast": "gado_used",
        "description": "description",
    }
    col_map = {}
    for i, h in enumerate(headers):
        h_clean = str(h).strip().lower()
        for alias, field in aliases.items():
            if alias in h_clean:
                col_map[i] = field
                break
    return col_map
