"""Excel import API routes (F-01)."""

import os
import time
from datetime import timedelta
from decimal import Decimal

from flask import request, jsonify, current_app
from werkzeug.utils import secure_filename

from app.import_engine import bp
from app.extensions import db
from app.models import BillingRecord
from app.utils import allowed_file

from ocdr.excel_reader import read_ocmri
from ocdr.config import get_payer, get_expected_rate


EXCEL_EXTENSIONS = {'.xlsx', '.xls'}


def _dict_to_billing_record(d: dict) -> BillingRecord:
    """Convert an excel_reader output dict to a BillingRecord model."""
    sd = d.get('service_date')
    carrier = d.get('insurance_carrier', '')
    modality = d.get('modality', '')
    is_psma = d.get('is_psma', False)
    gado = d.get('gado_used', False)

    # Compute appeal deadline using payer config
    payer_info = get_payer(carrier)
    appeal = sd + timedelta(days=payer_info['deadline']) if sd else None

    # Compute expected rate for underpayment detection
    expected = get_expected_rate(modality, carrier or 'DEFAULT', is_psma, gado)
    total = d.get('total_payment', Decimal('0')) or Decimal('0')
    if expected and expected > 0:
        pct = float(total / expected) if total > 0 else 0.0
        variance = total - expected
    else:
        pct = None
        variance = None

    return BillingRecord(
        patient_name=d.get('patient_name', ''),
        referring_doctor=d.get('referring_doctor', ''),
        scan_type=d.get('scan_type', ''),
        gado_used=gado,
        insurance_carrier=carrier,
        modality=modality,
        service_date=sd,
        primary_payment=d.get('primary_payment', 0),
        secondary_payment=d.get('secondary_payment', 0),
        total_payment=total,
        extra_charges=d.get('extra_charges', 0),
        reading_physician=d.get('reading_physician'),
        patient_id=d.get('patient_id'),
        birth_date=d.get('birth_date'),
        patient_name_display=d.get('patient_name_display'),
        schedule_date=d.get('schedule_date'),
        is_psma=is_psma,
        is_new_patient=d.get('is_new_patient', False),
        is_research=d.get('is_research', False),
        appeal_deadline=appeal,
        import_source='EXCEL_IMPORT',
        source=d.get('source', ''),
        notes=d.get('notes', ''),
        service_month=d.get('service_month', ''),
        service_year=d.get('service_year', ''),
        expected_rate=expected if expected and expected > 0 else None,
        variance=variance,
        pct_of_expected=round(pct, 4) if pct is not None else None,
    )


def _load_existing_keys():
    """Load all existing dedup keys into a set for O(1) lookups."""
    rows = BillingRecord.query.with_entities(
        BillingRecord.patient_name,
        BillingRecord.service_date,
        BillingRecord.scan_type,
        BillingRecord.modality,
    ).all()
    return {(r.patient_name, r.service_date, r.scan_type, r.modality) for r in rows}


def _make_dedup_key(d: dict):
    """Build the dedup key tuple from a record dict."""
    return (
        d.get('patient_name', ''),
        d.get('service_date'),
        d.get('scan_type', ''),
        d.get('modality', ''),
    )


@bp.route('/import/excel', methods=['POST'])
def import_excel():
    """Import billing records from an uploaded OCMRI Excel file."""
    start = time.time()

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename or not allowed_file(file.filename, EXCEL_EXTENSIONS):
        return jsonify({'error': 'Invalid file type. Accepted: .xlsx, .xls'}), 400

    filename = secure_filename(file.filename)
    upload_dir = current_app.config['UPLOAD_FOLDER']
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)

    try:
        records = read_ocmri(filepath)
    except Exception as e:
        # Clean up the uploaded file on parse failure
        try:
            os.remove(filepath)
        except OSError:
            pass
        return jsonify({'error': f'Failed to read Excel file: {str(e)}'}), 422

    # Load existing keys once for O(1) dedup instead of O(n) queries
    existing_keys = _load_existing_keys()

    imported = 0
    skipped = 0
    errors = []
    batch_size = current_app.config.get('IMPORT_BATCH_SIZE', 500)
    batch = []

    for i, d in enumerate(records):
        try:
            key = _make_dedup_key(d)
            if key in existing_keys:
                skipped += 1
                continue

            record = _dict_to_billing_record(d)
            batch.append(record)
            existing_keys.add(key)  # Prevent intra-batch duplicates

            if len(batch) >= batch_size:
                db.session.add_all(batch)
                db.session.flush()
                imported += len(batch)
                batch = []
        except Exception as e:
            errors.append({'row': i + 2, 'error': str(e)})

    # Flush remaining batch
    if batch:
        db.session.add_all(batch)
        db.session.flush()
        imported += len(batch)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Database error: {str(e)}'}), 500

    duration_ms = round((time.time() - start) * 1000)
    return jsonify({
        'imported': imported,
        'skipped': skipped,
        'errors': errors,
        'total_in_file': len(records),
        'duration_ms': duration_ms,
    })


@bp.route('/import/status', methods=['GET'])
def import_status():
    """Return current import statistics."""
    total = BillingRecord.query.count()
    latest = db.session.query(db.func.max(BillingRecord.created_at)).scalar()

    source_counts = (
        db.session.query(BillingRecord.import_source, db.func.count())
        .group_by(BillingRecord.import_source)
        .all()
    )

    return jsonify({
        'total_records': total,
        'latest_import': latest.isoformat() if latest else None,
        'has_data': total > 0,
        'by_source': {src or 'unknown': cnt for src, cnt in source_counts},
    })
