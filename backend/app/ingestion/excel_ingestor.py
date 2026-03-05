"""
Excel Import Engine (F-01).

Handles OCMRI.xlsx import: parses the 'Current' sheet, maps columns per DATA_SCHEMA,
converts Excel serial dates, deduplicates, and batch-inserts into billing_records.
"""

import io
import logging
from datetime import date, datetime, timedelta

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord

logger = logging.getLogger(__name__)

# Column index mapping (0-based) per BUILD_SPEC DATA_SCHEMA
COL_MAP = {
    0: "patient_name",        # A - Patient
    1: "referring_doctor",    # B - Doctor
    2: "scan_type",           # C - Scan
    3: "gado_used",           # D - Gado
    4: "insurance_carrier",   # E - Insurance
    5: "modality",            # F - Type
    6: "service_date",        # G - Date
    7: "primary_payment",     # H - Primary
    8: "secondary_payment",   # I - Secondary
    9: "total_payment",       # J - Total
    10: "extra_charges",      # K - Extra
    11: "reading_physician",  # L - ReadBy
    12: "patient_id",         # M - ID
    13: "birth_date",         # N - Birth Date
    14: "patient_name_display",  # O - Patient Name
    15: "schedule_date",      # P - S Date
    16: "modality_code",      # Q - Modalities
    17: "description",        # R - Description
    18: "service_month",      # S - Month
    19: "service_year",       # T - Year
    20: "is_new_patient",     # U - New
}

EXCEL_EPOCH = date(1899, 12, 30)
BATCH_SIZE = 500

# Payer codes that should be normalized to 'SELF PAY'
SELFPAY_VARIANTS = {"SELFPAY", "SELF-PAY", "SELF PAY", "CASH"}


def _excel_serial_to_date(serial) -> date | None:
    """Convert Excel serial date number to Python date."""
    if serial is None:
        return None
    if isinstance(serial, (datetime, date)):
        return serial if isinstance(serial, date) else serial.date()
    try:
        serial = int(float(serial))
        if serial < 1:
            return None
        return EXCEL_EPOCH + timedelta(days=serial)
    except (ValueError, TypeError, OverflowError):
        return None


def _parse_bool(val) -> bool:
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return str(val).strip().upper() in ("YES", "TRUE", "1", "Y")


def _clean_text(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip().upper()
    return s if s else None


def _parse_money(val) -> float:
    if val is None:
        return 0.0
    try:
        return round(float(val), 2)
    except (ValueError, TypeError):
        return 0.0


def _normalize_carrier(carrier: str) -> str:
    """Normalize insurance carrier code (BR-10)."""
    if carrier in SELFPAY_VARIANTS:
        return "SELF PAY"
    return carrier


def _derive_psma(description: str | None, modality: str | None) -> bool:
    """Detect PSMA PET scans (BR-02)."""
    if not description:
        return False
    desc_upper = description.upper()
    if "PSMA" in desc_upper:
        return True
    if modality == "PET" and ("GA-68" in desc_upper or "GALLIUM" in desc_upper):
        return True
    return False


def _parse_row(row: tuple) -> dict | None:
    """Parse a single Excel row into a dict for BillingRecord. Returns None if row is invalid."""
    patient_name = _clean_text(row[0]) if len(row) > 0 else None
    if not patient_name:
        return None

    referring_doctor = _clean_text(row[1]) if len(row) > 1 else None
    scan_type = _clean_text(row[2]) if len(row) > 2 else None
    insurance_carrier = _clean_text(row[4]) if len(row) > 4 else None
    modality = _clean_text(row[5]) if len(row) > 5 else None
    service_date = _excel_serial_to_date(row[6]) if len(row) > 6 else None

    # Required fields check
    if not all([referring_doctor, scan_type, insurance_carrier, modality, service_date]):
        return None

    insurance_carrier = _normalize_carrier(insurance_carrier)
    description = _clean_text(row[17]) if len(row) > 17 else None

    return {
        "patient_name": patient_name,
        "referring_doctor": referring_doctor,
        "scan_type": scan_type,
        "gado_used": _parse_bool(row[3]) if len(row) > 3 else False,
        "insurance_carrier": insurance_carrier,
        "modality": modality,
        "service_date": service_date,
        "primary_payment": _parse_money(row[7]) if len(row) > 7 else 0.0,
        "secondary_payment": _parse_money(row[8]) if len(row) > 8 else 0.0,
        "total_payment": _parse_money(row[9]) if len(row) > 9 else 0.0,
        "extra_charges": _parse_money(row[10]) if len(row) > 10 else 0.0,
        "reading_physician": _clean_text(row[11]) if len(row) > 11 else None,
        "patient_id": int(float(row[12])) if len(row) > 12 and row[12] is not None else None,
        "birth_date": _excel_serial_to_date(row[13]) if len(row) > 13 else None,
        "patient_name_display": _clean_text(row[14]) if len(row) > 14 else None,
        "schedule_date": _excel_serial_to_date(row[15]) if len(row) > 15 else None,
        "modality_code": _clean_text(row[16]) if len(row) > 16 else None,
        "description": description,
        "service_month": _clean_text(row[18]) if len(row) > 18 else None,
        "service_year": _clean_text(row[19]) if len(row) > 19 else None,
        "is_new_patient": _parse_bool(row[20]) if len(row) > 20 else None,
        "is_psma": _derive_psma(description, modality),
        "import_source": "EXCEL_IMPORT",
    }


async def import_excel(
    file_content: bytes,
    session: AsyncSession,
    sheet_name: str = "Current",
) -> dict:
    """
    Import an OCMRI Excel file into billing_records.

    Returns dict with imported, skipped, errors counts.
    """
    wb = load_workbook(filename=io.BytesIO(file_content), read_only=True, data_only=True)

    if sheet_name not in wb.sheetnames:
        available = ", ".join(wb.sheetnames)
        raise ValueError(f"Sheet '{sheet_name}' not found. Available: {available}")

    ws = wb[sheet_name]

    # Load existing dedup keys
    existing_result = await session.execute(
        select(
            BillingRecord.patient_name,
            BillingRecord.service_date,
            BillingRecord.scan_type,
            BillingRecord.modality,
        )
    )
    existing_keys = {
        (r[0], r[1], r[2], r[3]) for r in existing_result.fetchall()
    }

    imported = 0
    skipped = 0
    errors = 0
    batch: list[BillingRecord] = []

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        try:
            parsed = _parse_row(row)
            if parsed is None:
                skipped += 1
                continue

            dedup_key = (
                parsed["patient_name"],
                parsed["service_date"],
                parsed["scan_type"],
                parsed["modality"],
            )
            if dedup_key in existing_keys:
                skipped += 1
                continue

            # Validate before inserting
            from backend.app.analytics.data_validation import validate_billing_record
            validation_errors = [v for v in validate_billing_record(parsed) if v.severity == "ERROR"]
            if validation_errors:
                logger.warning(f"Row {row_idx} validation failed: {validation_errors[0].message}")
                errors += 1
                continue

            existing_keys.add(dedup_key)
            batch.append(BillingRecord(**parsed))
            imported += 1

            if len(batch) >= BATCH_SIZE:
                session.add_all(batch)
                await session.flush()
                batch = []

        except Exception as e:
            logger.warning(f"Row {row_idx} error: {e}")
            errors += 1

    # Flush remaining batch
    if batch:
        session.add_all(batch)
        await session.flush()

    await session.commit()
    wb.close()

    logger.info(f"Excel import complete: {imported} imported, {skipped} skipped, {errors} errors")
    return {"imported": imported, "skipped": skipped, "errors": errors}
