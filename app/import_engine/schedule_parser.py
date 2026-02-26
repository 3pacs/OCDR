"""Schedule PDF parser and calendar matching engine.

Extracts appointment/schedule data from PDF files and matches
scheduled scans to billing records for calendar visualization.

Handles common schedule PDF formats:
  - Daily scan schedules (patient name, time, scan type, modality)
  - Weekly schedule reports
  - Appointment lists
"""
import re
import os
from datetime import datetime, date, time as dtime

from flask import request, jsonify
from app.import_engine import import_bp
from app.models import db, BillingRecord, ScheduleEntry

import tempfile


# ---- Regex patterns for schedule data extraction ----

# Time patterns: 8:00 AM, 08:00, 8:00AM, 14:30
_TIME_RE = re.compile(
    r'\b(\d{1,2}:\d{2})\s*(AM|PM|am|pm)?\b'
)

# Date patterns for schedule headers
_DATE_HEADER_RE = re.compile(
    r'(?:date|schedule|day)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
    re.IGNORECASE
)

# Standalone date on a line (often schedule date headers)
_DATE_LINE_RE = re.compile(
    r'^[\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})[\s]*$|'
    r'(\w+day,?\s+\w+\s+\d{1,2},?\s+\d{4})',
    re.MULTILINE
)

# Modality keywords
_MODALITY_MAP = {
    'MRI': 'HMRI', 'HMRI': 'HMRI', 'OPEN MRI': 'OPEN', 'OPEN': 'OPEN',
    'CT': 'CT', 'CAT SCAN': 'CT', 'PET': 'PET', 'PET/CT': 'PET',
    'PET CT': 'PET', 'BONE': 'BONE', 'BONE SCAN': 'BONE',
    'X-RAY': 'DX', 'XRAY': 'DX', 'DX': 'DX',
}

# Scan type keywords
_SCAN_KEYWORDS = [
    'BRAIN', 'HEAD', 'SPINE', 'CERVICAL', 'THORACIC', 'LUMBAR',
    'CHEST', 'ABDOMEN', 'PELVIS', 'C.A.P', 'KNEE', 'SHOULDER',
    'HIP', 'ANKLE', 'WRIST', 'ELBOW', 'FOOT', 'HAND',
    'CARDIAC', 'BREAST', 'PROSTATE', 'PSMA', 'WHOLE BODY',
]

# Name pattern: LAST, FIRST (comma required to reduce false positives)
_NAME_RE = re.compile(r'\b([A-Z][A-Z\'-]{1,}),\s+([A-Z][A-Z\'-]{1,})\b')


def _parse_date_flexible(date_str):
    """Parse a date from various formats."""
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ('%m/%d/%Y', '%m/%d/%y', '%m-%d-%Y', '%Y-%m-%d',
                '%B %d, %Y', '%b %d, %Y', '%B %d %Y'):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(time_str, ampm=None):
    """Parse a time string to datetime.time."""
    try:
        parts = time_str.split(':')
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0

        if ampm:
            ampm = ampm.upper()
            if ampm == 'PM' and hour < 12:
                hour += 12
            elif ampm == 'AM' and hour == 12:
                hour = 0

        return dtime(hour, minute)
    except (ValueError, IndexError):
        return None


def _detect_modality(text):
    """Detect modality from text content."""
    upper = text.upper()
    for keyword, modality in _MODALITY_MAP.items():
        if keyword in upper:
            return modality
    return None


def _detect_scan_type(text):
    """Detect scan type/body part from text."""
    upper = text.upper()
    for keyword in _SCAN_KEYWORDS:
        if keyword in upper:
            return keyword
    return None


def parse_schedule_text(text, filename='unknown'):
    """Extract schedule entries from text content.

    Returns a dict with extracted appointments and stats.
    """
    lines = text.split('\n')
    entries = []
    current_date = None

    # First pass: find any date in the document for context
    for line in lines:
        date_match = _DATE_HEADER_RE.search(line)
        if date_match:
            current_date = _parse_date_flexible(date_match.group(1))
            if current_date:
                break

    if not current_date:
        for match in _DATE_LINE_RE.finditer(text):
            d = _parse_date_flexible(match.group(1) or match.group(2))
            if d:
                current_date = d
                break

    # Second pass: extract individual appointments
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Check if this line is a new date header
        date_match = _DATE_HEADER_RE.search(line_stripped)
        if date_match:
            d = _parse_date_flexible(date_match.group(1))
            if d:
                current_date = d
                continue

        # Check for standalone date line
        date_line = _DATE_LINE_RE.match(line_stripped)
        if date_line:
            d = _parse_date_flexible(date_line.group(1) or date_line.group(2))
            if d:
                current_date = d
                continue

        # Look for patient name
        name_match = _NAME_RE.search(line_stripped)
        if not name_match:
            continue

        patient_name = f'{name_match.group(1)}, {name_match.group(2)}'.upper()

        # Extract time
        appt_time = None
        time_match = _TIME_RE.search(line_stripped)
        if time_match:
            appt_time = _parse_time(time_match.group(1), time_match.group(2))

        # Extract modality and scan type from the line
        modality = _detect_modality(line_stripped)
        scan_type = _detect_scan_type(line_stripped)

        # If no modality in this line, check surrounding context
        if not modality:
            # Look at the full document for dominant modality
            modality = _detect_modality(text)

        entry = {
            'patient_name': patient_name,
            'schedule_date': current_date,
            'appointment_time': appt_time.isoformat() if appt_time else None,
            'modality': modality,
            'scan_type': scan_type,
            'source_line': line_stripped[:200],
        }
        entries.append(entry)

    return {
        'entries_found': len(entries),
        'schedule_date': current_date.isoformat() if current_date else None,
        'entries': entries,
    }


def import_schedule_pdf(filepath):
    """Import a schedule PDF file.

    Extracts text with pdfplumber, parses schedule entries,
    stores in ScheduleEntry table, and matches to billing records.
    """
    import pdfplumber

    filename = os.path.basename(filepath)
    all_text = ''

    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                all_text += page_text + '\n'

            # Also try tables
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row:
                        all_text += '\t'.join(str(cell) if cell else '' for cell in row) + '\n'

    if not all_text.strip():
        return {
            'entries_found': 0,
            'needs_ocr': True,
            'message': 'No selectable text in schedule PDF — requires OCR',
        }

    parsed = parse_schedule_text(all_text, filename)
    entries = parsed.get('entries', [])

    stored = 0
    matched = 0
    skipped = 0

    for entry in entries:
        sched_date = entry.get('schedule_date')
        patient_name = entry.get('patient_name')

        if not patient_name:
            skipped += 1
            continue

        # Check for existing schedule entry
        existing = ScheduleEntry.query.filter_by(
            patient_name=patient_name,
            schedule_date=sched_date,
        ).first()

        if existing:
            skipped += 1
            continue

        sched = ScheduleEntry(
            patient_name=patient_name,
            schedule_date=sched_date,
            appointment_time=entry.get('appointment_time'),
            modality=entry.get('modality'),
            scan_type=entry.get('scan_type'),
            source_file=filename,
        )
        db.session.add(sched)
        stored += 1

        # Try to match to a billing record
        billing_match = BillingRecord.query.filter_by(
            patient_name=patient_name,
        )
        if sched_date:
            billing_match = billing_match.filter_by(service_date=sched_date)
        billing_record = billing_match.first()

        if billing_record:
            sched.matched_billing_id = billing_record.id
            sched.match_status = 'MATCHED'
            matched += 1
        else:
            sched.match_status = 'UNMATCHED'

    db.session.commit()

    return {
        'entries_found': len(entries),
        'entries_stored': stored,
        'entries_matched': matched,
        'entries_skipped': skipped,
        'schedule_date': parsed.get('schedule_date'),
        'source': 'SCHEDULE_PDF',
    }


# ---- API Routes ----

@import_bp.route('/schedule', methods=['POST'])
def import_schedule():
    """POST /api/import/schedule - Upload a schedule PDF.

    Parses the PDF, extracts appointments, stores them,
    and matches to existing billing records.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    try:
        file.save(tmp_path)
        result = import_schedule_pdf(tmp_path)
        result['filename'] = file.filename
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@import_bp.route('/schedule/entries', methods=['GET'])
def list_schedule_entries():
    """GET /api/import/schedule/entries - List schedule entries with filters.

    Query params: date_from, date_to, modality, match_status, page, per_page
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    modality = request.args.get('modality')
    match_status = request.args.get('match_status')

    query = ScheduleEntry.query
    if date_from:
        query = query.filter(ScheduleEntry.schedule_date >= date_from)
    if date_to:
        query = query.filter(ScheduleEntry.schedule_date <= date_to)
    if modality:
        query = query.filter(ScheduleEntry.modality == modality.upper())
    if match_status:
        query = query.filter(ScheduleEntry.match_status == match_status.upper())

    query = query.order_by(ScheduleEntry.schedule_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'entries': [e.to_dict() for e in pagination.items],
        'total': pagination.total,
        'page': page,
        'pages': pagination.pages,
    })


@import_bp.route('/schedule/calendar', methods=['GET'])
def schedule_calendar_data():
    """GET /api/import/schedule/calendar - Calendar event data.

    Returns schedule entries and billing records formatted for calendar display.
    Query params: month (YYYY-MM), modality_group (mri or pet_ct)
    """
    month_str = request.args.get('month')
    modality_group = request.args.get('modality_group', 'mri')

    # Determine date range
    if month_str:
        try:
            year, month = map(int, month_str.split('-'))
        except ValueError:
            return jsonify({'error': 'Invalid month format, use YYYY-MM'}), 400
    else:
        today = date.today()
        year, month = today.year, today.month

    from calendar import monthrange
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])

    # Define modality groups
    if modality_group == 'mri':
        modalities = ('HMRI', 'OPEN')
        title = 'MRI Schedule'
    else:
        modalities = ('PET', 'CT', 'BONE')
        title = 'PET/CT Schedule'

    # Get scheduled appointments
    scheduled = ScheduleEntry.query.filter(
        ScheduleEntry.schedule_date >= first_day,
        ScheduleEntry.schedule_date <= last_day,
        ScheduleEntry.modality.in_(modalities),
    ).all()

    # Get billing records (actual scans performed)
    billed = BillingRecord.query.filter(
        BillingRecord.service_date >= first_day,
        BillingRecord.service_date <= last_day,
        BillingRecord.modality.in_(modalities),
    ).all()

    # Build events list
    events = []

    # Scheduled events (blue)
    for s in scheduled:
        event = {
            'id': f'sched-{s.id}',
            'title': s.patient_name,
            'date': s.schedule_date.isoformat() if s.schedule_date else None,
            'time': s.appointment_time,
            'type': 'scheduled',
            'modality': s.modality,
            'scan_type': s.scan_type,
            'matched': s.match_status == 'MATCHED',
            'color': '#0d6efd' if s.match_status == 'MATCHED' else '#dc3545',
        }
        events.append(event)

    # Billed events (green) — only those NOT already matched to a schedule entry
    matched_billing_ids = {
        s.matched_billing_id for s in scheduled if s.matched_billing_id
    }
    for b in billed:
        if b.id in matched_billing_ids:
            continue  # Already shown as matched scheduled event
        event = {
            'id': f'bill-{b.id}',
            'title': b.patient_name,
            'date': b.service_date.isoformat() if b.service_date else None,
            'type': 'billed',
            'modality': b.modality,
            'scan_type': b.scan_type,
            'total_payment': b.total_payment,
            'color': '#198754',
        }
        events.append(event)

    # Summary stats
    total_scheduled = len(scheduled)
    total_matched = sum(1 for s in scheduled if s.match_status == 'MATCHED')
    total_unmatched = total_scheduled - total_matched
    total_billed_only = len([e for e in events if e['type'] == 'billed'])

    return jsonify({
        'title': title,
        'month': f'{year}-{month:02d}',
        'modality_group': modality_group,
        'events': events,
        'summary': {
            'total_scheduled': total_scheduled,
            'total_matched': total_matched,
            'total_unmatched': total_unmatched,
            'total_billed_only': total_billed_only,
            'total_billed': len(billed),
        },
    })


@import_bp.route('/schedule/rematch', methods=['POST'])
def rematch_schedules():
    """POST /api/import/schedule/rematch - Re-run matching for unmatched entries.

    Useful after importing new billing records from Excel.
    """
    unmatched = ScheduleEntry.query.filter_by(match_status='UNMATCHED').all()
    matched_count = 0

    for entry in unmatched:
        billing_match = BillingRecord.query.filter_by(
            patient_name=entry.patient_name,
        )
        if entry.schedule_date:
            billing_match = billing_match.filter_by(service_date=entry.schedule_date)
        billing_record = billing_match.first()

        if billing_record:
            entry.matched_billing_id = billing_record.id
            entry.match_status = 'MATCHED'
            matched_count += 1

    db.session.commit()

    return jsonify({
        'total_unmatched_checked': len(unmatched),
        'newly_matched': matched_count,
        'still_unmatched': len(unmatched) - matched_count,
    })
