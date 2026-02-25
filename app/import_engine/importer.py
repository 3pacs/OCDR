"""Billing data importer — parses Excel and CSV files into BillingRecord rows.

Smart column detection: auto-maps source columns to BillingRecord fields
using fuzzy matching on header names.  User can override via column_mapping.

Handles:
  - .xlsx / .xls via openpyxl + pandas
  - .csv via pandas
  - Duplicate detection via patient_name + service_date + modality
  - Row-level error tracking
"""

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import pandas as pd

from app import db
from app.models import BillingRecord, ImportJob

log = logging.getLogger(__name__)

# ── Column mapping ──────────────────────────────────────────────

# Maps our BillingRecord fields to common column name variants
FIELD_ALIASES = {
    'patient_name':       ['patient name', 'patient', 'name', 'pat name', 'pt name',
                           'patient_name', 'patientname'],
    'referring_doctor':   ['referring doctor', 'referring', 'ref doctor', 'ref dr',
                           'ref physician', 'referring md', 'ordering', 'referring_doctor'],
    'scan_type':          ['scan type', 'exam', 'procedure', 'description', 'study',
                           'exam description', 'scan_type', 'study description'],
    'modality':           ['modality', 'mod', 'exam type', 'type', 'modality type'],
    'service_date':       ['service date', 'date', 'exam date', 'dos', 'date of service',
                           'service_date', 'svc date', 'study date'],
    'insurance_carrier':  ['insurance', 'carrier', 'payer', 'ins', 'insurance carrier',
                           'insurance_carrier', 'plan', 'primary insurance'],
    'primary_payment':    ['primary payment', 'primary', 'primary pay', 'pri payment',
                           'primary_payment', 'payment'],
    'secondary_payment':  ['secondary payment', 'secondary', 'secondary pay', 'sec payment',
                           'secondary_payment'],
    'total_payment':      ['total payment', 'total', 'total pay', 'amount paid',
                           'total_payment', 'paid', 'reimbursement'],
    'extra_charges':      ['extra charges', 'extra', 'charges', 'additional',
                           'extra_charges', 'other charges'],
    'gado_used':          ['gado', 'gadolinium', 'contrast', 'gado used', 'gado_used', 'w/'],
    'reading_physician':  ['reading physician', 'reading', 'radiologist', 'reader',
                           'interpreting', 'reading_physician', 'read by'],
    'patient_id':         ['patient id', 'mrn', 'id', 'chart', 'patient_id', 'pt id',
                           'medical record number'],
    'birth_date':         ['birth date', 'dob', 'date of birth', 'birthdate', 'birth_date',
                           'd.o.b'],
    'description':        ['description', 'notes', 'comment', 'details'],
    'is_psma':            ['psma', 'is psma', 'is_psma', 'psma pet'],
    'denial_status':      ['denial', 'denial status', 'denied', 'denial_status'],
    'denial_reason_code': ['denial reason', 'reason code', 'cas code', 'denial_reason_code'],
    'era_claim_id':       ['era claim', 'claim id', 'era', 'era_claim_id', 'accession'],
}


def auto_detect_columns(df):
    """Map DataFrame columns to BillingRecord fields.

    Returns dict {billing_field: source_column_name}
    """
    mapping = {}
    source_cols = {col: col.strip().lower() for col in df.columns}

    for field, aliases in FIELD_ALIASES.items():
        for src_col, src_lower in source_cols.items():
            if src_lower in aliases:
                mapping[field] = src_col
                break

    return mapping


def preview_file(file_path):
    """Read a file and return preview data + auto-detected column mapping.

    Returns dict with:
      columns: list of source column names
      sample_rows: first 10 rows as list of dicts
      auto_mapping: auto-detected {billing_field: source_col}
      total_rows: total row count
    """
    df = _read_file(file_path)

    mapping = auto_detect_columns(df)

    sample = df.head(10).fillna('').to_dict(orient='records')

    return {
        'columns': list(df.columns),
        'sample_rows': sample,
        'auto_mapping': mapping,
        'total_rows': len(df),
    }


def run_import(file_path, job_id, column_mapping=None):
    """Import billing records from file.

    Args:
        file_path: Path to the uploaded file
        job_id: ImportJob.id for status tracking
        column_mapping: Optional override {billing_field: source_col}

    Returns summary dict.
    """
    job = ImportJob.query.get(job_id)
    job.status = 'processing'
    db.session.commit()

    try:
        df = _read_file(file_path)
        job.total_rows = len(df)

        # Use provided mapping or auto-detect
        mapping = column_mapping or auto_detect_columns(df)
        job.column_mapping = json.dumps(mapping)
        db.session.commit()

        imported = 0
        skipped = 0
        error_count = 0
        errors = []

        for idx, row in df.iterrows():
            row_num = idx + 2  # 1-indexed + header row
            try:
                record_data = _map_row(row, mapping)

                if not record_data.get('patient_name'):
                    skipped += 1
                    continue

                # Duplicate check
                if _is_duplicate(record_data):
                    skipped += 1
                    continue

                record = BillingRecord(
                    import_source='EXCEL_IMPORT' if file_path.endswith(('.xlsx', '.xls')) else 'CSV_UPLOAD',
                    **record_data,
                )
                db.session.add(record)
                imported += 1

                # Batch commit every 100 rows
                if imported % 100 == 0:
                    db.session.commit()

            except Exception as exc:
                error_count += 1
                errors.append({'row': row_num, 'error': str(exc)})
                if error_count > 50:
                    errors.append({'row': 0, 'error': 'Too many errors, stopping'})
                    break

        db.session.commit()

        job.status = 'completed'
        job.imported_rows = imported
        job.skipped_rows = skipped
        job.error_rows = error_count
        job.errors = json.dumps(errors) if errors else None
        job.completed_at = datetime.now(timezone.utc)
        db.session.commit()

        return {
            'imported': imported,
            'skipped': skipped,
            'errors': error_count,
            'error_details': errors[:10],
            'mapping_used': mapping,
        }

    except Exception as exc:
        job.status = 'failed'
        job.error_message = str(exc)
        db.session.commit()
        raise


def _read_file(file_path):
    """Read Excel or CSV into a pandas DataFrame."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ('.xlsx', '.xls'):
        df = pd.read_excel(file_path, engine='openpyxl')
    elif ext == '.csv':
        df = pd.read_csv(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    # Clean column names
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _map_row(row, mapping):
    """Convert a DataFrame row to a BillingRecord field dict."""
    data = {}

    for field, src_col in mapping.items():
        if src_col not in row.index:
            continue
        val = row[src_col]
        if pd.isna(val):
            continue

        # Type coercion per field
        if field in ('primary_payment', 'secondary_payment', 'total_payment', 'extra_charges'):
            data[field] = _to_decimal(val)
        elif field in ('service_date', 'birth_date', 'appeal_deadline'):
            data[field] = _to_date(val)
        elif field == 'patient_id':
            data[field] = int(float(val)) if val else None
        elif field in ('gado_used', 'is_psma'):
            data[field] = _to_bool(val)
        else:
            data[field] = str(val).strip()

    # Defaults for required fields
    data.setdefault('patient_name', '')
    data.setdefault('referring_doctor', '')
    data.setdefault('scan_type', '')
    data.setdefault('insurance_carrier', '')
    data.setdefault('modality', '')

    return data


def _is_duplicate(data):
    """Check if a record with same patient + date + modality already exists."""
    if not data.get('service_date') or not data.get('patient_name'):
        return False

    return BillingRecord.query.filter_by(
        patient_name=data['patient_name'],
        service_date=data['service_date'],
        modality=data.get('modality', ''),
    ).first() is not None


def _to_decimal(val):
    try:
        s = str(val).replace('$', '').replace(',', '').strip()
        return Decimal(s) if s else Decimal(0)
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _to_date(val):
    if isinstance(val, datetime):
        return val.date()
    if hasattr(val, 'date'):
        return val
    s = str(val).strip()
    for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%m-%d-%Y', '%m-%d-%y', '%Y/%m/%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _to_bool(val):
    s = str(val).strip().lower()
    return s in ('true', '1', 'yes', 'y', 'x', 'w/', 'gad')
