"""Smart CSV import engine.

Auto-detects column mappings by fuzzy-matching header names to expected fields.
Handles various vendor CSV formats with different column names and orderings.
"""
import csv
import os
import time
from datetime import datetime, date, timedelta

from app.models import db, BillingRecord, Payer
from app.import_engine.excel_importer import (
    normalize_carrier, detect_psma, compute_appeal_deadline,
    parse_bool, parse_float, parse_int, excel_serial_to_date,
)

# Expected field names and their common aliases across vendors
FIELD_ALIASES = {
    'patient_name': [
        'patient name', 'patient', 'name', 'pt name', 'pt_name',
        'patient_name', 'patientname', 'member name', 'member',
    ],
    'referring_doctor': [
        'referring doctor', 'referring', 'ref doctor', 'ref physician',
        'referring_doctor', 'doctor', 'physician', 'ordering physician',
    ],
    'scan_type': [
        'scan type', 'scan_type', 'exam type', 'procedure', 'exam',
        'study type', 'study', 'procedure type',
    ],
    'gado_used': [
        'gado', 'gado used', 'gado_used', 'gadolinium', 'contrast',
        'with contrast', 'contrast used',
    ],
    'insurance_carrier': [
        'insurance', 'carrier', 'insurance carrier', 'insurance_carrier',
        'payer', 'payer name', 'ins carrier', 'ins', 'plan',
    ],
    'modality': [
        'modality', 'mod', 'modality code', 'equipment', 'machine type',
    ],
    'service_date': [
        'service date', 'service_date', 'dos', 'date of service',
        'exam date', 'study date', 'date', 'svc date',
    ],
    'primary_payment': [
        'primary payment', 'primary_payment', 'primary', 'pri payment',
        'primary pay', 'pri pay', 'insurance payment',
    ],
    'secondary_payment': [
        'secondary payment', 'secondary_payment', 'secondary', 'sec payment',
        'secondary pay', 'sec pay',
    ],
    'total_payment': [
        'total payment', 'total_payment', 'total', 'payment', 'amount paid',
        'paid amount', 'paid', 'total paid',
    ],
    'extra_charges': [
        'extra charges', 'extra_charges', 'extra', 'additional charges',
        'other charges', 'misc charges',
    ],
    'reading_physician': [
        'reading physician', 'reading_physician', 'radiologist',
        'reading doctor', 'reader', 'interpreting physician',
    ],
    'patient_id': [
        'patient id', 'patient_id', 'patientid', 'mrn', 'medical record',
        'chart number', 'acct', 'account',
    ],
    'description': [
        'description', 'desc', 'procedure description', 'exam description',
        'study description', 'notes',
    ],
    'schedule_date': [
        'schedule date', 'schedule_date', 'scheduled', 'appt date',
        'appointment date', 'scheduled date',
    ],
}


def _normalize_header(header):
    """Normalize a column header for matching."""
    return header.strip().lower().replace('_', ' ').replace('-', ' ')


def _match_columns(headers):
    """Map CSV headers to our expected field names using fuzzy matching.

    Returns a dict of {field_name: column_index}.
    """
    mapping = {}
    normalized = [_normalize_header(h) for h in headers]

    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            for idx, norm_header in enumerate(normalized):
                if norm_header == alias or alias in norm_header:
                    if field not in mapping:
                        mapping[field] = idx
                    break
            if field in mapping:
                break

    return mapping


def _parse_csv_date(val):
    """Parse a date from CSV (could be various formats)."""
    if not val or not val.strip():
        return None
    val = val.strip()

    # Try as Excel serial number
    try:
        serial = int(float(val))
        if 30000 < serial < 60000:  # Reasonable date range
            return excel_serial_to_date(serial)
    except (ValueError, TypeError):
        pass

    # Try standard date formats
    for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%m-%d-%Y',
                '%d-%b-%Y', '%b %d, %Y', '%m/%d/%Y %H:%M'):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue

    return None


def import_csv_file(filepath, delimiter=','):
    """Import a CSV file with auto-detected column mapping.

    Returns stats dict similar to excel importer.
    """
    start = time.time()
    imported = 0
    skipped = 0
    errors = []
    batch = []

    with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
        # Detect dialect
        sample = f.read(8192)
        f.seek(0)

        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',\t|;')
            reader = csv.reader(f, dialect)
        except csv.Error:
            reader = csv.reader(f, delimiter=delimiter)

        # Read header row
        try:
            headers = next(reader)
        except StopIteration:
            return {'imported': 0, 'skipped': 0, 'errors': ['Empty CSV file'],
                    'duration_ms': 0}

        mapping = _match_columns(headers)

        if 'patient_name' not in mapping:
            return {
                'imported': 0, 'skipped': 0,
                'errors': ['Could not detect patient name column'],
                'columns_detected': {k: headers[v] for k, v in mapping.items()},
                'duration_ms': 0,
            }

        for row_idx, row in enumerate(reader, start=2):
            try:
                if not row or all(not cell.strip() for cell in row):
                    skipped += 1
                    continue

                def get(field, default=None):
                    idx = mapping.get(field)
                    if idx is not None and idx < len(row):
                        val = row[idx].strip()
                        return val if val else default
                    return default

                patient_name = get('patient_name')
                if not patient_name:
                    skipped += 1
                    continue
                patient_name = patient_name.strip().upper()

                service_date = _parse_csv_date(get('service_date', ''))
                if not service_date:
                    skipped += 1
                    continue

                referring_doctor = (get('referring_doctor', '') or '').strip().upper()
                scan_type = (get('scan_type', '') or '').strip().upper()
                gado_used = parse_bool(get('gado_used'))
                insurance_carrier = normalize_carrier(get('insurance_carrier', ''))
                modality = (get('modality', '') or '').strip().upper()
                primary_payment = parse_float(get('primary_payment', '0'))
                secondary_payment = parse_float(get('secondary_payment', '0'))
                total_payment = parse_float(get('total_payment', '0'))
                extra_charges = parse_float(get('extra_charges', '0'))
                reading_physician = (get('reading_physician') or '').strip().upper() or None
                patient_id = parse_int(get('patient_id'))
                description = get('description')
                schedule_date = _parse_csv_date(get('schedule_date', ''))

                # BR-02: PSMA detection
                is_psma = detect_psma(description)

                # Dedup check
                existing = BillingRecord.query.filter_by(
                    patient_name=patient_name,
                    service_date=service_date,
                    scan_type=scan_type,
                    modality=modality,
                ).first()
                if existing:
                    skipped += 1
                    continue

                appeal_deadline = compute_appeal_deadline(service_date, insurance_carrier)

                record = BillingRecord(
                    patient_name=patient_name,
                    referring_doctor=referring_doctor,
                    scan_type=scan_type,
                    gado_used=gado_used,
                    insurance_carrier=insurance_carrier,
                    modality=modality,
                    service_date=service_date,
                    primary_payment=primary_payment,
                    secondary_payment=secondary_payment,
                    total_payment=total_payment,
                    extra_charges=extra_charges,
                    reading_physician=reading_physician,
                    patient_id=patient_id,
                    description=description,
                    schedule_date=schedule_date,
                    is_psma=is_psma,
                    appeal_deadline=appeal_deadline,
                    import_source='CSV_IMPORT',
                )
                batch.append(record)
                imported += 1

                if len(batch) >= 500:
                    db.session.add_all(batch)
                    db.session.commit()
                    batch = []

            except Exception as e:
                errors.append(f'Row {row_idx}: {str(e)}')

    if batch:
        db.session.add_all(batch)
        db.session.commit()

    duration_ms = int((time.time() - start) * 1000)

    return {
        'imported': imported,
        'skipped': skipped,
        'errors': errors,
        'columns_detected': {k: headers[v] for k, v in mapping.items() if v < len(headers)},
        'duration_ms': duration_ms,
    }
