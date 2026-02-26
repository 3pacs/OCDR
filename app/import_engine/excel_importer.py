"""F-01: Excel Import Engine for OCMRI.xlsx"""
import time
from datetime import date, datetime, timedelta

from flask import request, jsonify
from app.import_engine import import_bp
from app.models import db, BillingRecord, Payer

# Excel epoch: date(1899, 12, 30)
EXCEL_EPOCH = date(1899, 12, 30)

# BR-10: SELFPAY normalization
SELFPAY_VARIANTS = {'SELFPAY', 'SELF-PAY', 'SELF PAY', 'CASH'}


def excel_serial_to_date(serial):
    """Convert an Excel serial date number to a Python date."""
    if serial is None:
        return None
    try:
        serial = int(float(serial))
        if serial < 1:
            return None
        return EXCEL_EPOCH + timedelta(days=serial)
    except (ValueError, TypeError, OverflowError):
        return None


def normalize_carrier(carrier):
    """Normalize insurance carrier code (BR-10)."""
    if not carrier:
        return carrier
    carrier = carrier.strip().upper()
    if carrier in SELFPAY_VARIANTS:
        return 'SELF PAY'
    return carrier


def detect_psma(description):
    """BR-02: Detect PSMA from description."""
    if not description:
        return False
    desc_upper = description.upper()
    return 'PSMA' in desc_upper or 'GA-68' in desc_upper or 'GALLIUM' in desc_upper


def compute_appeal_deadline(service_date, carrier_code):
    """Compute appeal deadline from service date and payer filing deadline."""
    payer = Payer.query.get(carrier_code)
    if payer and service_date:
        return service_date + timedelta(days=payer.filing_deadline_days)
    # Default to 180 days if payer not found
    if service_date:
        return service_date + timedelta(days=180)
    return None


def parse_bool(val):
    """Parse boolean from Excel cell."""
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return str(val).strip().upper() in ('YES', 'TRUE', '1', 'Y')


def parse_float(val):
    """Parse float from Excel cell, default 0.0."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def parse_int(val):
    """Parse integer from Excel cell."""
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def import_excel_file(filepath):
    """Import an Excel workbook from the given path. Returns stats dict."""
    import openpyxl

    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    # Try 'Current' sheet first, fall back to first sheet
    if 'Current' in wb.sheetnames:
        ws = wb['Current']
    else:
        ws = wb.active

    start = time.time()
    imported = 0
    skipped = 0
    errors = []
    batch = []

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        try:
            if not row or len(row) < 10:
                skipped += 1
                continue

            patient_name = str(row[0]).strip().upper() if row[0] else None
            if not patient_name:
                skipped += 1
                continue

            referring_doctor = str(row[1]).strip().upper() if row[1] else ''
            scan_type = str(row[2]).strip().upper() if row[2] else ''
            gado_used = parse_bool(row[3])
            insurance_carrier = normalize_carrier(str(row[4]) if row[4] else '')
            modality = str(row[5]).strip().upper() if row[5] else ''

            # Service date - handle both serial and date objects
            service_date = None
            if isinstance(row[6], (datetime, date)):
                service_date = row[6] if isinstance(row[6], date) else row[6].date()
            else:
                service_date = excel_serial_to_date(row[6])

            if not service_date:
                skipped += 1
                continue

            primary_payment = parse_float(row[7])
            secondary_payment = parse_float(row[8])
            total_payment = parse_float(row[9])
            extra_charges = parse_float(row[10]) if len(row) > 10 else 0.0
            reading_physician = str(row[11]).strip().upper() if len(row) > 11 and row[11] else None
            patient_id = parse_int(row[12]) if len(row) > 12 else None

            # Birth date (col N = index 13)
            birth_date = None
            if len(row) > 13 and row[13]:
                if isinstance(row[13], (datetime, date)):
                    birth_date = row[13] if isinstance(row[13], date) else row[13].date()
                else:
                    birth_date = excel_serial_to_date(row[13])

            # Schedule date (col P = index 15)
            schedule_date = None
            if len(row) > 15 and row[15]:
                if isinstance(row[15], (datetime, date)):
                    schedule_date = row[15] if isinstance(row[15], date) else row[15].date()
                else:
                    schedule_date = excel_serial_to_date(row[15])

            # Modality code (col Q = index 16)
            modality_code = str(row[16]).strip().upper() if len(row) > 16 and row[16] else None

            # Description (col R = index 17)
            description = str(row[17]).strip() if len(row) > 17 and row[17] else None

            # Is new patient (col U = index 20)
            is_new_patient = parse_bool(row[20]) if len(row) > 20 else False

            # BR-02: PSMA detection
            is_psma = detect_psma(description)

            # Dedup check: patient_name + service_date + scan_type + modality
            existing = BillingRecord.query.filter_by(
                patient_name=patient_name,
                service_date=service_date,
                scan_type=scan_type,
                modality=modality,
            ).first()

            if existing:
                skipped += 1
                continue

            # Compute appeal deadline
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
                birth_date=birth_date,
                schedule_date=schedule_date,
                modality_code=modality_code,
                description=description,
                is_new_patient=is_new_patient,
                is_psma=is_psma,
                appeal_deadline=appeal_deadline,
                import_source='EXCEL_IMPORT',
            )
            batch.append(record)
            imported += 1

            # Batch insert every 500 rows
            if len(batch) >= 500:
                db.session.add_all(batch)
                db.session.commit()
                batch = []

        except Exception as e:
            errors.append(f'Row {row_idx}: {str(e)}')

    # Insert remaining batch
    if batch:
        db.session.add_all(batch)
        db.session.commit()

    wb.close()
    duration_ms = int((time.time() - start) * 1000)

    return {
        'imported': imported,
        'skipped': skipped,
        'errors': errors,
        'duration_ms': duration_ms,
    }


@import_bp.route('/excel', methods=['POST'])
def import_excel():
    """POST /api/import/excel - Upload and import OCMRI.xlsx"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    import tempfile
    import os
    # Save to temp file
    fd, tmp_path = tempfile.mkstemp(suffix='.xlsx')
    os.close(fd)
    try:
        file.save(tmp_path)
        result = import_excel_file(tmp_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@import_bp.route('/status', methods=['GET'])
def import_status():
    """GET /api/import/status - Import status"""
    total = BillingRecord.query.count()
    last = BillingRecord.query.order_by(BillingRecord.created_at.desc()).first()
    return jsonify({
        'total_records': total,
        'last_import': last.created_at.isoformat() if last and last.created_at else None,
        'source': last.import_source if last else None,
    })
