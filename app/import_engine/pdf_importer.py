"""PDF Import Engine (F-12).

Extracts billing data from digital PDFs using pdfplumber.
Falls back to basic text extraction if pdfplumber unavailable.
"""

import os
import re
from datetime import datetime

from app.models import db, BillingRecord


try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


def _parse_date(val):
    """Parse date from common formats."""
    if not val:
        return None
    val = str(val).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(val):
    if not val:
        return 0.0
    try:
        return float(str(val).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return 0.0


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

                    svc_date = _parse_date(data.get("service_date"))
                    if not svc_date:
                        result["skipped"] += 1
                        continue

                    rec = BillingRecord(
                        patient_name=patient,
                        referring_doctor=str(data.get("referring_doctor", "")).strip() or "UNKNOWN",
                        scan_type=str(data.get("scan_type", "")).strip() or "UNKNOWN",
                        modality=str(data.get("modality", "")).strip().upper() or "HMRI",
                        insurance_carrier=str(data.get("insurance_carrier", "")).strip() or "UNKNOWN",
                        service_date=svc_date,
                        total_payment=_parse_float(data.get("total_payment")),
                        primary_payment=_parse_float(data.get("primary_payment")),
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

    batch = []
    for line in lines:
        dates = date_pattern.findall(line)
        amounts = money_pattern.findall(line)

        if dates and len(line) > 20:
            # Heuristic: line has a date and is long enough to be a data row
            svc_date = _parse_date(dates[0])
            if not svc_date:
                continue

            # Extract name (text before the first date)
            name_part = line[:line.index(dates[0])].strip()
            if len(name_part) < 3:
                continue

            total = _parse_float(amounts[-1]) if amounts else 0.0

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
        "insurance": "insurance_carrier", "carrier": "insurance_carrier", "payer": "insurance_carrier",
    }
    col_map = {}
    for i, h in enumerate(headers):
        h_clean = str(h).strip().lower()
        for alias, field in aliases.items():
            if alias in h_clean:
                col_map[i] = field
                break
    return col_map
