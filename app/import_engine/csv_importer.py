"""CSV Import Engine (F-12).

Auto-detects column mapping from headers using fuzzy matching.
Supports billing records and schedule records.
"""

import csv
import os
from datetime import datetime, date

from app.models import db, BillingRecord, ScheduleRecord


# Column aliases for auto-detection
BILLING_ALIASES = {
    "patient": "patient_name", "patient name": "patient_name", "name": "patient_name",
    "doctor": "referring_doctor", "referring doctor": "referring_doctor", "referring": "referring_doctor",
    "scan": "scan_type", "scan type": "scan_type", "procedure": "scan_type",
    "gado": "gado_used", "contrast": "gado_used",
    "insurance": "insurance_carrier", "carrier": "insurance_carrier", "payer": "insurance_carrier",
    "type": "modality", "modality": "modality",
    "date": "service_date", "service date": "service_date", "dos": "service_date",
    "primary": "primary_payment", "primary payment": "primary_payment",
    "secondary": "secondary_payment", "secondary payment": "secondary_payment",
    "total": "total_payment", "total payment": "total_payment",
    "extra": "extra_charges", "extra charges": "extra_charges",
    "read by": "reading_physician", "reading physician": "reading_physician",
    "description": "description",
}

SCHEDULE_ALIASES = {
    "patient": "patient_name", "patient name": "patient_name", "name": "patient_name",
    "scan": "scan_type", "scan type": "scan_type", "procedure": "scan_type",
    "type": "modality", "modality": "modality",
    "date": "scheduled_date", "scheduled date": "scheduled_date", "appt date": "scheduled_date",
    "time": "scheduled_time", "scheduled time": "scheduled_time", "appt time": "scheduled_time",
    "doctor": "referring_doctor", "referring doctor": "referring_doctor",
    "insurance": "insurance_carrier", "carrier": "insurance_carrier",
    "location": "location", "site": "location",
    "status": "status",
    "notes": "notes",
}


def _detect_columns(headers, alias_map):
    """Auto-detect column mapping from headers."""
    col_map = {}
    for i, h in enumerate(headers):
        norm = h.strip().lower().replace("_", " ")
        if norm in alias_map:
            col_map[i] = alias_map[norm]
    return col_map


def _parse_date(val):
    """Parse date from string."""
    if not val or not str(val).strip():
        return None
    val = str(val).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y", "%Y%m%d"):
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


def _is_billing_csv(col_map, alias_map):
    """Determine if CSV maps to billing records."""
    billing_fields = set(col_map.values())
    return "patient_name" in billing_fields and ("service_date" in billing_fields or "total_payment" in billing_fields)


def import_csv(filepath):
    """Import a CSV file, auto-detecting whether it's billing or schedule data.

    Returns dict: {imported, skipped, errors, total_rows, record_type}
    """
    result = {"imported": 0, "skipped": 0, "errors": [], "total_rows": 0,
              "record_type": "unknown", "filename": os.path.basename(filepath)}

    try:
        with open(filepath, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            if not headers:
                result["errors"].append("Empty CSV file")
                return result

            # Try billing mapping first, then schedule
            billing_map = _detect_columns(headers, BILLING_ALIASES)
            schedule_map = _detect_columns(headers, SCHEDULE_ALIASES)

            if _is_billing_csv(billing_map, BILLING_ALIASES):
                return _import_billing_csv(reader, billing_map, result)
            elif schedule_map and "patient_name" in schedule_map.values():
                return _import_schedule_csv(reader, schedule_map, result)
            else:
                result["errors"].append(f"Cannot detect CSV format. Headers: {headers[:10]}")
                return result

    except Exception as e:
        result["errors"].append(str(e))
        return result


def _import_billing_csv(reader, col_map, result):
    """Import billing records from CSV rows."""
    result["record_type"] = "billing"
    batch = []

    for row_idx, row in enumerate(reader, start=2):
        result["total_rows"] += 1
        try:
            data = {}
            for col_idx, field in col_map.items():
                if col_idx < len(row):
                    data[field] = row[col_idx]

            patient_name = str(data.get("patient_name", "")).strip()
            if not patient_name:
                result["skipped"] += 1
                continue

            service_date = _parse_date(data.get("service_date"))
            if not service_date:
                result["skipped"] += 1
                continue

            rec = BillingRecord(
                patient_name=patient_name,
                referring_doctor=str(data.get("referring_doctor", "")).strip() or "UNKNOWN",
                scan_type=str(data.get("scan_type", "")).strip() or "UNKNOWN",
                gado_used=str(data.get("gado_used", "")).strip().upper() in ("Y", "YES", "TRUE", "1"),
                insurance_carrier=str(data.get("insurance_carrier", "")).strip() or "UNKNOWN",
                modality=str(data.get("modality", "")).strip().upper() or "HMRI",
                service_date=service_date,
                primary_payment=_parse_float(data.get("primary_payment")),
                secondary_payment=_parse_float(data.get("secondary_payment")),
                total_payment=_parse_float(data.get("total_payment")),
                extra_charges=_parse_float(data.get("extra_charges")),
                reading_physician=str(data.get("reading_physician", "")).strip() or None,
                description=str(data.get("description", "")).strip() or None,
                import_source="CSV_UPLOAD",
            )
            batch.append(rec)

            if len(batch) >= 500:
                db.session.bulk_save_objects(batch)
                db.session.commit()
                result["imported"] += len(batch)
                batch = []

        except Exception as e:
            result["errors"].append(f"Row {row_idx}: {e}")

    if batch:
        db.session.bulk_save_objects(batch)
        db.session.commit()
        result["imported"] += len(batch)

    return result


def _import_schedule_csv(reader, col_map, result):
    """Import schedule records from CSV rows."""
    result["record_type"] = "schedule"
    batch = []

    for row_idx, row in enumerate(reader, start=2):
        result["total_rows"] += 1
        try:
            data = {}
            for col_idx, field in col_map.items():
                if col_idx < len(row):
                    data[field] = row[col_idx]

            patient_name = str(data.get("patient_name", "")).strip()
            if not patient_name:
                result["skipped"] += 1
                continue

            scheduled_date = _parse_date(data.get("scheduled_date"))
            if not scheduled_date:
                result["skipped"] += 1
                continue

            rec = ScheduleRecord(
                patient_name=patient_name,
                scan_type=str(data.get("scan_type", "")).strip() or "UNKNOWN",
                modality=str(data.get("modality", "")).strip().upper() or "HMRI",
                scheduled_date=scheduled_date,
                scheduled_time=str(data.get("scheduled_time", "")).strip() or None,
                referring_doctor=str(data.get("referring_doctor", "")).strip() or None,
                insurance_carrier=str(data.get("insurance_carrier", "")).strip() or None,
                location=str(data.get("location", "")).strip() or None,
                status=str(data.get("status", "SCHEDULED")).strip().upper(),
                notes=str(data.get("notes", "")).strip() or None,
                import_source="CSV_UPLOAD",
            )
            batch.append(rec)

            if len(batch) >= 500:
                db.session.bulk_save_objects(batch)
                db.session.commit()
                result["imported"] += len(batch)
                batch = []

        except Exception as e:
            result["errors"].append(f"Row {row_idx}: {e}")

    if batch:
        db.session.bulk_save_objects(batch)
        db.session.commit()
        result["imported"] += len(batch)

    return result
