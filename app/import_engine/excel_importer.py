"""Excel Import Engine for billing records (F-01).

Imports billing data from Excel workbooks (.xlsx) into billing_records table.
Supports the OCMRI.xlsx format with column mapping, date conversion,
deduplication, and batch inserts.
"""

import os
from datetime import datetime, date, timedelta

import openpyxl

from app.models import db, BillingRecord


# Column mapping: Excel header → model field (with aliases)
COLUMN_MAP = {
    "patient": "patient_name",
    "patient name": "patient_name",
    "name": "patient_name",
    "doctor": "referring_doctor",
    "referring doctor": "referring_doctor",
    "ref doctor": "referring_doctor",
    "referring": "referring_doctor",
    "scan": "scan_type",
    "scan type": "scan_type",
    "procedure": "scan_type",
    "gado": "gado_used",
    "contrast": "gado_used",
    "gadolinium": "gado_used",
    "insurance": "insurance_carrier",
    "insurance carrier": "insurance_carrier",
    "carrier": "insurance_carrier",
    "payer": "insurance_carrier",
    "type": "modality",
    "modality": "modality",
    "modalities": "modality",
    "date": "service_date",
    "service date": "service_date",
    "s date": "service_date",
    "dos": "service_date",
    "primary": "primary_payment",
    "primary payment": "primary_payment",
    "secondary": "secondary_payment",
    "secondary payment": "secondary_payment",
    "total": "total_payment",
    "total payment": "total_payment",
    "extra": "extra_charges",
    "extra charges": "extra_charges",
    "read by": "reading_physician",
    "reading physician": "reading_physician",
    "readby": "reading_physician",
    "id": "patient_id",
    "patient id": "patient_id",
    "description": "description",
    "desc": "description",
}

# Modality normalization
MODALITY_MAP = {
    "MRI": "HMRI", "HMRI": "HMRI", "HIGH FIELD MRI": "HMRI",
    "CT": "CT", "CAT": "CT", "CAT SCAN": "CT",
    "PET": "PET", "PET/CT": "PET", "PET CT": "PET",
    "BONE": "BONE", "BONE DENSITY": "BONE", "DEXA": "BONE",
    "OPEN": "OPEN", "OPEN MRI": "OPEN",
    "DX": "DX", "X-RAY": "DX", "XRAY": "DX",
}

# Insurance carrier normalization
CARRIER_NORMALIZE = {
    "SELFPAY": "SELF PAY", "SELF-PAY": "SELF PAY",
    "SELF PAY": "SELF PAY", "CASH": "SELF PAY",
    "MEDICARE": "M/M", "MEDICAID": "M/M", "MEDI-CAL": "M/M",
}

# Excel serial date epoch
EXCEL_EPOCH = datetime(1899, 12, 30)


def _normalize_header(header):
    """Normalize a header string for column mapping."""
    if not header:
        return ""
    return str(header).strip().lower().replace("_", " ")


def _parse_date(val):
    """Parse a date value from Excel (serial number or string)."""
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val if isinstance(val, date) else val.date()
    if isinstance(val, (int, float)):
        try:
            return (EXCEL_EPOCH + timedelta(days=int(val))).date()
        except (ValueError, OverflowError):
            return None
    val_str = str(val).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(val_str, fmt).date()
        except ValueError:
            continue
    return None


def _parse_bool(val):
    """Parse boolean from Excel (Y/N/TRUE/FALSE/1/0)."""
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    s = str(val).strip().upper()
    return s in ("Y", "YES", "TRUE", "1", "X", "GAD", "GADO")


def _parse_float(val):
    """Parse float from Excel."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = str(val).replace(",", "").replace("$", "").strip()
        return float(cleaned) if cleaned else 0.0
    except (ValueError, TypeError):
        return 0.0


def _normalize_modality(val):
    """Normalize modality string."""
    if not val:
        return "HMRI"
    return MODALITY_MAP.get(str(val).strip().upper(), str(val).strip().upper())


def _normalize_carrier(val):
    """Normalize insurance carrier."""
    if not val:
        return "UNKNOWN"
    upper = str(val).strip().upper()
    return CARRIER_NORMALIZE.get(upper, str(val).strip().upper())


def _detect_psma(description):
    """Detect PSMA scans from description."""
    if not description:
        return False
    upper = str(description).upper()
    return "PSMA" in upper or "GA-68" in upper or "GALLIUM" in upper


def import_excel(filepath, sheet_name=None):
    """Import billing records from an Excel file.

    Args:
        filepath: Path to .xlsx file
        sheet_name: Sheet to read (default: first sheet or 'Current')

    Returns:
        dict with keys: imported, skipped, errors, total_rows
    """
    result = {"imported": 0, "skipped": 0, "errors": [], "total_rows": 0, "filename": os.path.basename(filepath)}

    try:
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    except Exception as e:
        result["errors"].append(f"Cannot open workbook: {e}")
        return result

    # Select sheet
    if sheet_name and sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
    elif "Current" in wb.sheetnames:
        ws = wb["Current"]
    else:
        ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        result["errors"].append("Empty sheet")
        return result

    # Map headers
    raw_headers = [str(h).strip() if h else "" for h in rows[0]]
    col_map = {}
    for i, h in enumerate(raw_headers):
        norm = _normalize_header(h)
        if norm in COLUMN_MAP:
            col_map[i] = COLUMN_MAP[norm]

    if not col_map:
        result["errors"].append(f"No recognized columns. Headers found: {raw_headers[:10]}")
        return result

    # Build dedup set from existing records
    existing = set()
    for rec in db.session.query(
        BillingRecord.patient_name, BillingRecord.service_date,
        BillingRecord.scan_type, BillingRecord.modality
    ).all():
        existing.add((rec.patient_name, rec.service_date, rec.scan_type, rec.modality))

    data_rows = rows[1:]
    result["total_rows"] = len(data_rows)
    batch = []
    batch_size = 500

    for row_idx, row in enumerate(data_rows, start=2):
        try:
            record_data = {}
            for col_idx, field_name in col_map.items():
                if col_idx < len(row):
                    record_data[field_name] = row[col_idx]

            # Required fields
            patient_name = str(record_data.get("patient_name", "")).strip()
            if not patient_name:
                continue

            service_date = _parse_date(record_data.get("service_date"))
            if not service_date:
                result["skipped"] += 1
                continue

            scan_type = str(record_data.get("scan_type", "")).strip() or "UNKNOWN"
            modality = _normalize_modality(record_data.get("modality"))
            referring_doctor = str(record_data.get("referring_doctor", "")).strip() or "UNKNOWN"

            # Dedup check
            dedup_key = (patient_name, service_date, scan_type, modality)
            if dedup_key in existing:
                result["skipped"] += 1
                continue
            existing.add(dedup_key)

            description = str(record_data.get("description", "")).strip() if record_data.get("description") else None

            rec = BillingRecord(
                patient_name=patient_name,
                referring_doctor=referring_doctor,
                scan_type=scan_type,
                gado_used=_parse_bool(record_data.get("gado_used")),
                insurance_carrier=_normalize_carrier(record_data.get("insurance_carrier")),
                modality=modality,
                service_date=service_date,
                primary_payment=_parse_float(record_data.get("primary_payment")),
                secondary_payment=_parse_float(record_data.get("secondary_payment")),
                total_payment=_parse_float(record_data.get("total_payment")),
                extra_charges=_parse_float(record_data.get("extra_charges")),
                reading_physician=str(record_data.get("reading_physician", "")).strip() or None,
                patient_id=int(_parse_float(record_data.get("patient_id"))) if record_data.get("patient_id") else None,
                description=description,
                is_psma=_detect_psma(description),
                import_source="EXCEL_IMPORT",
            )
            batch.append(rec)

            if len(batch) >= batch_size:
                db.session.bulk_save_objects(batch)
                db.session.commit()
                result["imported"] += len(batch)
                batch = []

        except Exception as e:
            result["errors"].append(f"Row {row_idx}: {e}")

    # Final batch
    if batch:
        db.session.bulk_save_objects(batch)
        db.session.commit()
        result["imported"] += len(batch)

    wb.close()
    return result
