"""Schedule PDF parser and calendar matching engine.

Extracts appointment/schedule data from PDF files and matches
scheduled scans to billing records for calendar visualization.

Handles common schedule PDF formats:
  - Daily scan schedules (patient name, time, scan type, modality)
  - Weekly schedule reports
  - Appointment lists
  - Scanned/image PDFs via OCR fallback

Features:
  - Single file upload or folder scan (recursively finds all PDFs/images)
  - pdfplumber text extraction with OCR fallback for scanned documents
  - Editable schedule entries with status tracking
  - Automatic matching to billing records
"""
import re
import os
from datetime import datetime, date, time as dtime

from flask import request, jsonify
from app.import_engine import import_bp
from app.models import db, BillingRecord, ScheduleRecord

import tempfile


# ---- Regex patterns for schedule data extraction ----

# Time patterns: 8:00 AM, 08:00, 8:00AM, 14:30
_TIME_RE = re.compile(
    r'\b(\d{1,2}:\d{2})\s*(AM|PM|am|pm)?\b'
)

# Date patterns for schedule headers
_DATE_HEADER_RE = re.compile(
    r'(?:date|schedule|day)[:\s\-]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
    re.IGNORECASE
)

# Standalone date on a line (often schedule date headers)
_DATE_LINE_RE = re.compile(
    r'^[\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})[\s]*$|'
    r'(\w+day,?\s+\w+\s+\d{1,2},?\s+\d{4})',
    re.MULTILINE
)

# Date anywhere in text (broader catch)
_DATE_ANYWHERE_RE = re.compile(
    r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b'
)

# Date from filename: "2026 0202.pdf" → 2026-02-02, "02-02-2026.pdf", "20260202.pdf"
_FILENAME_DATE_RE = re.compile(
    r'(\d{4})\s*(\d{2})(\d{2})|'  # YYYY MMDD or YYYYMMDD
    r'(\d{2})[/-](\d{2})[/-](\d{4})|'  # MM-DD-YYYY
    r'(\d{4})[/-](\d{2})[/-](\d{2})'  # YYYY-MM-DD
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

# Name patterns (multiple strategies, ordered by specificity)
# 1. LAST, FIRST (comma separated — most reliable)
_NAME_COMMA_RE = re.compile(r'\b([A-Z][A-Z\'-]{1,}),\s*([A-Z][A-Z\'-]{1,})\b')
# 2. FIRST LAST (space separated, 2+ chars each, at line start or after time/tab)
_NAME_SPACE_RE = re.compile(r'(?:^|\t|(?:\d{1,2}:\d{2}\s*(?:AM|PM)?)\s+)([A-Z][a-zA-Z\'-]{1,})\s+([A-Z][a-zA-Z\'-]{1,})\b')
# 3. Any two capitalized words that look like names (fallback)
_NAME_CAPS_RE = re.compile(r'\b([A-Z]{2,})\s+([A-Z]{2,})\b')

# File extensions for schedule folder scanning
_SCHEDULE_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.txt', '.csv', '.xlsx', '.xls'}


def _parse_date_flexible(date_str):
    """Parse a date from various formats."""
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ('%m/%d/%Y', '%m/%d/%y', '%m-%d-%Y', '%m-%d-%y',
                '%Y-%m-%d', '%Y/%m/%d',
                '%B %d, %Y', '%b %d, %Y', '%B %d %Y', '%b %d %Y'):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def _extract_date_from_filename(filename):
    """Extract a date from a filename like '2026 0202.pdf' or '02-02-2026.pdf'."""
    basename = os.path.splitext(os.path.basename(filename))[0]
    m = _FILENAME_DATE_RE.search(basename)
    if not m:
        return None

    try:
        if m.group(1):  # YYYY MMDD or YYYYMMDD
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif m.group(4):  # MM-DD-YYYY
            return date(int(m.group(6)), int(m.group(4)), int(m.group(5)))
        elif m.group(7):  # YYYY-MM-DD
            return date(int(m.group(7)), int(m.group(8)), int(m.group(9)))
    except (ValueError, TypeError):
        pass
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
    Uses multiple strategies: date headers, filename dates, and
    flexible name patterns (comma-separated, space-separated, all-caps).
    """
    lines = text.split('\n')
    entries = []
    current_date = None

    # Try extracting date from filename first (e.g., "2026 0202.pdf")
    filename_date = _extract_date_from_filename(filename)

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

    # Broader search: any date-like string in the text
    if not current_date:
        for match in _DATE_ANYWHERE_RE.finditer(text):
            d = _parse_date_flexible(match.group(1))
            if d:
                current_date = d
                break

    # Fall back to filename date
    if not current_date and filename_date:
        current_date = filename_date

    # Detect dominant modality from the full document
    doc_modality = _detect_modality(text)

    # Collect all skip-words (header/label text to filter out)
    _skip_words = {
        'PATIENT', 'NAME', 'DATE', 'TIME', 'MODALITY', 'TYPE', 'DOCTOR',
        'PHYSICIAN', 'INSURANCE', 'STATUS', 'NOTES', 'SCHEDULE', 'SCAN',
        'APPOINTMENT', 'SCHEDULED', 'PAGE', 'TOTAL', 'REPORT',
    }

    # Second pass: extract individual appointments
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped or len(line_stripped) < 4:
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

        # Inline date in the line (update current_date)
        inline_date_match = _DATE_ANYWHERE_RE.search(line_stripped)
        if inline_date_match:
            d = _parse_date_flexible(inline_date_match.group(1))
            if d:
                current_date = d

        # Look for patient name using multiple strategies
        patient_name = None

        # Strategy 1: LAST, FIRST (comma separated — most reliable)
        name_match = _NAME_COMMA_RE.search(line_stripped)
        if name_match:
            patient_name = f'{name_match.group(1)}, {name_match.group(2)}'.upper()

        # Strategy 2: FIRST LAST after time or at start of tab-delimited line
        if not patient_name:
            name_match = _NAME_SPACE_RE.search(line_stripped)
            if name_match:
                first, last = name_match.group(1).upper(), name_match.group(2).upper()
                if first not in _skip_words and last not in _skip_words:
                    patient_name = f'{last}, {first}'

        # Strategy 3: Two consecutive ALL-CAPS words (common in schedules)
        if not patient_name:
            name_match = _NAME_CAPS_RE.search(line_stripped)
            if name_match:
                w1, w2 = name_match.group(1), name_match.group(2)
                if (w1 not in _skip_words and w2 not in _skip_words
                        and len(w1) >= 2 and len(w2) >= 2):
                    patient_name = f'{w1}, {w2}'

        if not patient_name:
            continue

        # Extract time
        appt_time = None
        time_match = _TIME_RE.search(line_stripped)
        if time_match:
            appt_time = _parse_time(time_match.group(1), time_match.group(2))

        # Extract modality and scan type from the line
        modality = _detect_modality(line_stripped) or doc_modality
        scan_type = _detect_scan_type(line_stripped)

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


def _extract_text_from_pdf(filepath):
    """Extract text from PDF using pdfplumber, with OCR fallback for scanned pages.

    Returns (text, used_ocr) tuple.
    """
    import pdfplumber

    all_text = ''
    used_ocr = False

    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            # Try direct text extraction first
            page_text = page.extract_text()
            if page_text and len(page_text.strip()) > 30:
                all_text += page_text + '\n'
                continue

            # Try tables
            tables = page.extract_tables()
            table_text = ''
            for table in tables:
                for row in table:
                    if row:
                        table_text += '\t'.join(str(cell) if cell else '' for cell in row) + '\n'
            if table_text.strip():
                all_text += table_text
                continue

            # Fall back to OCR for this page
            ocr_text = _ocr_pdf_page(page)
            if ocr_text:
                all_text += ocr_text + '\n'
                used_ocr = True

    return all_text, used_ocr


def _ocr_pdf_page(page):
    """OCR a single PDF page by rendering to image."""
    try:
        page_image = page.to_image(resolution=300)
        img_path = tempfile.mktemp(suffix='.png')
        try:
            page_image.save(img_path)
            return _ocr_image_file(img_path)
        finally:
            if os.path.exists(img_path):
                os.unlink(img_path)
    except Exception:
        return None


def _ocr_image_file(filepath):
    """OCR a single image file. Returns extracted text or None.

    Tries multiple OCR strategies in order:
    1. pytesseract with Pillow (lightweight, no cv2 needed)
    2. pytesseract with cv2 preprocessing (better for noisy scans)
    """
    # Strategy 1: Pillow + pytesseract (most portable)
    try:
        import pytesseract
        from PIL import Image, ImageFilter, ImageOps

        img = Image.open(filepath)
        # Preprocess: grayscale, sharpen, threshold
        img = ImageOps.grayscale(img)
        img = img.filter(ImageFilter.SHARPEN)
        # Simple threshold to clean up scanned text
        img = img.point(lambda x: 0 if x < 140 else 255, '1')

        text = pytesseract.image_to_string(img, config='--psm 6 --oem 3')
        if text and text.strip():
            return text
    except ImportError:
        pass  # pytesseract not installed, try cv2 below
    except Exception:
        pass

    # Strategy 2: cv2 + pytesseract (better preprocessing)
    try:
        import cv2
        import pytesseract

        image = cv2.imread(filepath)
        if image is None:
            return None

        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
        thresh = cv2.adaptiveThreshold(
            denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        text = pytesseract.image_to_string(thresh, config='--psm 6 --oem 3')
        return text if text.strip() else None
    except ImportError:
        return None
    except Exception:
        return None


def _store_schedule_entries(entries, filename, used_ocr=False):
    """Store parsed schedule entries in the database and match to billing.

    If OCR was used, applies learned corrections before storing.
    Returns summary dict with counts.
    """
    corrections_applied = 0
    if used_ocr:
        try:
            from app.import_engine.ocr_learner import apply_corrections_to_entries
            corrections_applied = apply_corrections_to_entries(entries)
        except Exception:
            pass  # Don't break import if learner fails

    stored = 0
    matched = 0
    skipped = 0

    for entry in entries:
        sched_date = entry.get('schedule_date')
        patient_name = entry.get('patient_name')

        if not patient_name:
            skipped += 1
            continue

        # scheduled_date is NOT NULL — skip entries without a date
        if not sched_date:
            skipped += 1
            continue

        # Check for existing schedule entry (dedup)
        existing = ScheduleRecord.query.filter_by(
            patient_name=patient_name,
            scheduled_date=sched_date,
        ).first()

        if existing:
            skipped += 1
            continue

        sched = ScheduleRecord(
            patient_name=patient_name,
            scheduled_date=sched_date,
            scheduled_time=entry.get('appointment_time'),
            modality=entry.get('modality') or 'HMRI',
            scan_type=entry.get('scan_type') or entry.get('modality') or 'UNKNOWN',
            source_file=filename,
            ocr_source=used_ocr,
            import_source='SCHEDULE_PARSER',
        )
        db.session.add(sched)
        stored += 1

        # Try to match to a billing record
        try:
            billing_match = BillingRecord.query.filter_by(
                patient_name=patient_name,
            )
            if sched_date:
                billing_match = billing_match.filter_by(service_date=sched_date)
            billing_record = billing_match.first()

            if billing_record:
                sched.matched_billing_id = billing_record.id
                sched.match_status = 'MATCHED'
                sched.status = 'COMPLETED'
                matched += 1
            else:
                sched.match_status = 'UNMATCHED'
        except Exception:
            sched.match_status = 'UNMATCHED'

    db.session.commit()

    return {
        'entries_stored': stored,
        'entries_matched': matched,
        'entries_skipped': skipped,
        'corrections_applied': corrections_applied,
    }


def import_schedule_pdf(filepath):
    """Import a schedule PDF file.

    Extracts text with pdfplumber (OCR fallback for scanned pages),
    parses schedule entries, stores in ScheduleRecord table, and matches
    to billing records.
    """
    filename = os.path.basename(filepath)

    try:
        all_text, used_ocr = _extract_text_from_pdf(filepath)
    except Exception:
        # If pdfplumber fails entirely, try pure OCR
        all_text = _ocr_image_file(filepath) or ''
        used_ocr = True if all_text else False

    if not all_text.strip():
        # Check which OCR deps are available for the error message
        ocr_status = []
        try:
            import pytesseract
            ocr_status.append('pytesseract: installed')
        except ImportError:
            ocr_status.append('pytesseract: NOT installed (pip install pytesseract)')
        try:
            from PIL import Image
            ocr_status.append('Pillow: installed')
        except ImportError:
            ocr_status.append('Pillow: NOT installed (pip install Pillow)')

        return {
            'entries_found': 0,
            'needs_ocr': True,
            'message': (
                'Could not extract text from this PDF. '
                'It appears to be a scanned image. '
                'Install OCR: pip install pytesseract Pillow, '
                'and ensure Tesseract OCR is installed on your system '
                '(apt install tesseract-ocr or download from github.com/tesseract-ocr/tesseract). '
                'OCR status: ' + '; '.join(ocr_status)
            ),
        }

    parsed = parse_schedule_text(all_text, filename)
    entries = parsed.get('entries', [])

    result = _store_schedule_entries(entries, filename, used_ocr)

    result['entries_found'] = len(entries)
    result['schedule_date'] = parsed.get('schedule_date')
    result['source'] = 'SCHEDULE_PDF'
    result['used_ocr'] = used_ocr
    return result


def import_schedule_image(filepath):
    """Import a schedule from an image file (PNG, JPG, TIFF, BMP).

    Uses OCR to extract text, then parses schedule entries.
    """
    filename = os.path.basename(filepath)
    text = _ocr_image_file(filepath)

    if not text or not text.strip():
        return {
            'entries_found': 0,
            'message': 'OCR could not extract readable text from image',
        }

    parsed = parse_schedule_text(text, filename)
    entries = parsed.get('entries', [])

    result = _store_schedule_entries(entries, filename, used_ocr=True)

    result['entries_found'] = len(entries)
    result['schedule_date'] = parsed.get('schedule_date')
    result['source'] = 'SCHEDULE_IMAGE_OCR'
    result['used_ocr'] = True
    return result


def import_schedule_text_file(filepath):
    """Import a schedule from a plain text file."""
    filename = os.path.basename(filepath)
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()

    if not text.strip():
        return {'entries_found': 0, 'message': 'Empty file'}

    parsed = parse_schedule_text(text, filename)
    entries = parsed.get('entries', [])

    result = _store_schedule_entries(entries, filename, used_ocr=False)

    result['entries_found'] = len(entries)
    result['schedule_date'] = parsed.get('schedule_date')
    result['source'] = 'SCHEDULE_TEXT'
    return result


def import_schedule_file(filepath):
    """Import a single schedule file of any type.

    Detects the file type and routes to the appropriate importer.
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext == '.pdf':
        return import_schedule_pdf(filepath)
    elif ext in ('.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp'):
        return import_schedule_image(filepath)
    elif ext == '.txt':
        return import_schedule_text_file(filepath)
    elif ext == '.csv':
        from app.import_engine.schedule_importer import import_csv
        count, errors = import_csv(filepath)
        return {
            'entries_found': count + len(errors),
            'entries_stored': count,
            'entries_matched': 0,
            'entries_skipped': len(errors),
            'source': 'SCHEDULE_CSV',
            'errors': errors,
        }
    elif ext in ('.xlsx', '.xls'):
        from app.import_engine.schedule_importer import import_excel
        count, errors = import_excel(filepath)
        return {
            'entries_found': count + len(errors),
            'entries_stored': count,
            'entries_matched': 0,
            'entries_skipped': len(errors),
            'source': 'SCHEDULE_EXCEL',
            'errors': errors,
        }
    else:
        return {'status': 'error', 'reason': f'Unsupported file type: {ext}'}


def scan_schedule_folder(folder_path):
    """Recursively scan a folder for schedule files and import them all.

    Handles PDFs (with OCR fallback), images, and text files.
    Returns a summary of the entire scan.
    """
    if not os.path.isdir(folder_path):
        return {'error': f'Folder not found: {folder_path}'}

    total_found = 0
    total_imported = 0
    total_entries = 0
    total_matched = 0
    total_skipped = 0
    total_ocr = 0
    files_errored = 0
    details = []

    for root, _dirs, files in os.walk(folder_path):
        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _SCHEDULE_EXTENSIONS:
                continue

            total_found += 1
            filepath = os.path.join(root, fname)

            try:
                result = import_schedule_file(filepath)

                entries_found = result.get('entries_found', 0)
                entries_stored = result.get('entries_stored', 0)
                entries_matched = result.get('entries_matched', 0)
                entries_skipped = result.get('entries_skipped', 0)

                total_entries += entries_found
                total_matched += entries_matched
                total_skipped += entries_skipped

                if entries_stored > 0:
                    total_imported += 1

                if result.get('used_ocr'):
                    total_ocr += 1

                detail = {
                    'filename': fname,
                    'status': 'imported' if entries_stored > 0 else 'skipped',
                    'entries_found': entries_found,
                    'entries_stored': entries_stored,
                    'entries_matched': entries_matched,
                    'used_ocr': result.get('used_ocr', False),
                }
                if result.get('message'):
                    detail['message'] = result['message']
                details.append(detail)

            except Exception as e:
                files_errored += 1
                details.append({
                    'filename': fname,
                    'status': 'error',
                    'reason': str(e),
                })

    return {
        'folder': folder_path,
        'total_files_found': total_found,
        'files_with_new_entries': total_imported,
        'files_errored': files_errored,
        'total_entries_found': total_entries,
        'total_entries_matched': total_matched,
        'total_entries_skipped': total_skipped,
        'files_using_ocr': total_ocr,
        'details': details,
    }


# ---- API Routes ----

@import_bp.route('/schedule', methods=['POST'])
def import_schedule():
    """POST /api/import/schedule - Upload a schedule PDF/image.

    Parses the file (with OCR for scanned docs), extracts appointments,
    stores them, and matches to existing billing records.
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
        result = import_schedule_file(tmp_path)
        result['filename'] = file.filename
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@import_bp.route('/schedule/scan-folder', methods=['POST'])
def scan_schedule_folder_endpoint():
    """POST /api/import/schedule/scan-folder - Scan a folder for schedule files.

    Recursively finds all PDFs, images, and text files in the given folder,
    extracts schedule data (using OCR when needed), and stores entries.

    JSON body: { "folder_path": "/path/to/schedules" }
    """
    data = request.get_json(silent=True)
    if not data or 'folder_path' not in data:
        return jsonify({'error': 'Provide folder_path in JSON body'}), 400

    folder_path = data['folder_path'].strip()
    if not os.path.isdir(folder_path):
        return jsonify({'error': f'Folder not found: {folder_path}'}), 400

    result = scan_schedule_folder(folder_path)
    return jsonify(result)


@import_bp.route('/schedule/entries', methods=['GET'])
def list_schedule_entries():
    """GET /api/import/schedule/entries - List schedule entries with filters.

    Query params: date_from, date_to, modality, match_status, status, page, per_page
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    modality = request.args.get('modality')
    match_status = request.args.get('match_status')
    status = request.args.get('status')

    query = ScheduleRecord.query
    if date_from:
        query = query.filter(ScheduleRecord.scheduled_date >= date_from)
    if date_to:
        query = query.filter(ScheduleRecord.scheduled_date <= date_to)
    if modality:
        query = query.filter(ScheduleRecord.modality == modality.upper())
    if match_status:
        query = query.filter(ScheduleRecord.match_status == match_status.upper())
    if status:
        query = query.filter(ScheduleRecord.status == status.upper())

    query = query.order_by(ScheduleRecord.scheduled_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'entries': [e.to_dict() for e in pagination.items],
        'total': pagination.total,
        'page': page,
        'pages': pagination.pages,
    })


@import_bp.route('/schedule/entries/<int:entry_id>', methods=['GET'])
def get_schedule_entry(entry_id):
    """GET /api/import/schedule/entries/<id> - Get a single schedule entry."""
    entry = db.session.get(ScheduleRecord, entry_id)
    if not entry:
        return jsonify({'error': 'Entry not found'}), 404
    return jsonify(entry.to_dict())


@import_bp.route('/schedule/entries/<int:entry_id>', methods=['PUT'])
def update_schedule_entry(entry_id):
    """PUT /api/import/schedule/entries/<id> - Update a schedule entry.

    JSON body can include any editable field:
    patient_name, schedule_date, appointment_time, modality, scan_type,
    status, notes, referring_doctor, insurance_carrier
    """
    entry = db.session.get(ScheduleRecord, entry_id)
    if not entry:
        return jsonify({'error': 'Entry not found'}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Provide JSON body'}), 400

    # Editable fields
    if 'patient_name' in data:
        entry.patient_name = data['patient_name'].strip().upper()
    if 'schedule_date' in data:
        if data['schedule_date']:
            entry.scheduled_date = datetime.strptime(data['schedule_date'], '%Y-%m-%d').date()
        else:
            entry.scheduled_date = None
    if 'appointment_time' in data:
        entry.scheduled_time = data['appointment_time']
    if 'modality' in data:
        entry.modality = data['modality'].upper() if data['modality'] else None
    if 'scan_type' in data:
        entry.scan_type = data['scan_type'].upper() if data['scan_type'] else None
    if 'status' in data:
        valid_statuses = ('SCHEDULED', 'COMPLETED', 'CANCELLED', 'NO_SHOW')
        status_val = data['status'].upper()
        if status_val in valid_statuses:
            entry.status = status_val
    if 'notes' in data:
        entry.notes = data['notes']
    if 'referring_doctor' in data:
        entry.referring_doctor = data['referring_doctor']
    if 'insurance_carrier' in data:
        entry.insurance_carrier = data['insurance_carrier']

    db.session.commit()

    # Re-run matching if name or date changed
    if 'patient_name' in data or 'schedule_date' in data:
        _rematch_single(entry)
        db.session.commit()

    return jsonify(entry.to_dict())


@import_bp.route('/schedule/entries/<int:entry_id>', methods=['DELETE'])
def delete_schedule_entry(entry_id):
    """DELETE /api/import/schedule/entries/<id> - Delete a schedule entry."""
    entry = db.session.get(ScheduleRecord, entry_id)
    if not entry:
        return jsonify({'error': 'Entry not found'}), 404

    db.session.delete(entry)
    db.session.commit()

    return jsonify({'deleted': entry_id})


@import_bp.route('/schedule/entries', methods=['POST'])
def create_schedule_entry():
    """POST /api/import/schedule/entries - Create a new schedule entry manually.

    JSON body: { patient_name, schedule_date, appointment_time, modality,
                 scan_type, notes, referring_doctor, insurance_carrier }
    """
    data = request.get_json(silent=True)
    if not data or 'patient_name' not in data:
        return jsonify({'error': 'patient_name is required'}), 400

    sched_date = date.today()
    if data.get('schedule_date'):
        try:
            sched_date = datetime.strptime(data['schedule_date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format, use YYYY-MM-DD'}), 400

    entry = ScheduleRecord(
        patient_name=data['patient_name'].strip().upper(),
        scheduled_date=sched_date,
        scheduled_time=data.get('appointment_time'),
        modality=data.get('modality', '').upper() if data.get('modality') else 'HMRI',
        scan_type=data.get('scan_type', '').upper() if data.get('scan_type') else 'UNKNOWN',
        status=data.get('status', 'SCHEDULED').upper(),
        notes=data.get('notes'),
        referring_doctor=data.get('referring_doctor'),
        insurance_carrier=data.get('insurance_carrier'),
        source_file='MANUAL',
        import_source='MANUAL',
    )
    db.session.add(entry)

    # Try to match
    _rematch_single(entry)

    db.session.commit()

    return jsonify(entry.to_dict()), 201


def _rematch_single(entry):
    """Try to match a single schedule entry to a billing record."""
    billing_match = BillingRecord.query.filter_by(
        patient_name=entry.patient_name,
    )
    if entry.scheduled_date:
        billing_match = billing_match.filter_by(service_date=entry.scheduled_date)
    billing_record = billing_match.first()

    if billing_record:
        entry.matched_billing_id = billing_record.id
        entry.match_status = 'MATCHED'
    else:
        entry.matched_billing_id = None
        entry.match_status = 'UNMATCHED'


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

    # Get scheduled appointments (exclude cancelled)
    scheduled = ScheduleRecord.query.filter(
        ScheduleRecord.scheduled_date >= first_day,
        ScheduleRecord.scheduled_date <= last_day,
        ScheduleRecord.modality.in_(modalities),
        ScheduleRecord.status != 'CANCELLED',
    ).all()

    # Get billing records (actual scans performed)
    billed = BillingRecord.query.filter(
        BillingRecord.service_date >= first_day,
        BillingRecord.service_date <= last_day,
        BillingRecord.modality.in_(modalities),
    ).all()

    # Build events list
    events = []

    # Scheduled events
    for s in scheduled:
        event = {
            'id': f'sched-{s.id}',
            'entry_id': s.id,
            'title': s.patient_name,
            'date': s.scheduled_date.isoformat() if s.scheduled_date else None,
            'time': s.scheduled_time,
            'type': 'scheduled',
            'modality': s.modality,
            'scan_type': s.scan_type,
            'status': s.status,
            'notes': s.notes,
            'matched': s.match_status == 'MATCHED',
            'color': '#0d6efd' if s.match_status == 'MATCHED' else '#dc3545',
            'ocr_source': s.ocr_source,
        }
        if s.status == 'NO_SHOW':
            event['color'] = '#6c757d'
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
    total_no_show = sum(1 for s in scheduled if s.status == 'NO_SHOW')

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
            'total_no_show': total_no_show,
        },
    })


@import_bp.route('/schedule/ocr-review', methods=['POST'])
def ocr_review_upload():
    """POST /api/import/schedule/ocr-review - Upload a handwritten PDF for OCR review.

    Extracts text via OCR, parses schedule entries, applies learned corrections,
    and returns the results for user review BEFORE storing to database.
    The user can correct OCR mistakes, then confirm to import.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp'):
        return jsonify({'error': 'File must be PDF or image for OCR review'}), 400

    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    try:
        file.save(tmp_path)

        # Extract text via OCR
        if ext == '.pdf':
            try:
                all_text, used_ocr = _extract_text_from_pdf(tmp_path)
            except Exception:
                all_text = _ocr_image_file(tmp_path) or ''
                used_ocr = True
        else:
            all_text = _ocr_image_file(tmp_path) or ''
            used_ocr = True

        if not all_text.strip():
            return jsonify({
                'entries': [],
                'raw_text': '',
                'message': 'Could not extract text. Ensure Tesseract OCR is installed.',
                'needs_ocr': True,
            })

        # Parse schedule entries
        parsed = parse_schedule_text(all_text, file.filename)
        entries = parsed.get('entries', [])

        # Apply learned corrections
        corrections_applied = 0
        try:
            from app.import_engine.ocr_learner import apply_corrections_to_entries
            corrections_applied = apply_corrections_to_entries(entries)
        except Exception:
            pass

        return jsonify({
            'filename': file.filename,
            'raw_text': all_text[:5000],
            'schedule_date': parsed.get('schedule_date'),
            'entries': entries,
            'entries_found': len(entries),
            'corrections_applied': corrections_applied,
            'used_ocr': used_ocr,
            'message': 'Review entries below. Correct any OCR mistakes, then confirm import.',
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@import_bp.route('/schedule/ocr-confirm', methods=['POST'])
def ocr_confirm_import():
    """POST /api/import/schedule/ocr-confirm - Confirm reviewed OCR entries.

    After user reviews and corrects OCR output, this stores the entries
    and learns from any corrections made.

    JSON body: {
        "filename": "schedule.pdf",
        "entries": [
            {"patient_name": "WILLIAMS, ROBERT", "schedule_date": "2026-02-27", ...},
            ...
        ],
        "corrections": [
            {"ocr_text": "W1LLIAMS, R0BERT", "corrected_text": "WILLIAMS, ROBERT", "field_type": "patient_name"},
            ...
        ]
    }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Provide JSON body'}), 400

    filename = data.get('filename', 'unknown')
    entries = data.get('entries', [])
    corrections = data.get('corrections', [])

    # Store user corrections for future learning
    corrections_stored = 0
    if corrections:
        try:
            from app.import_engine.ocr_learner import store_bulk_corrections
            corrections_stored = store_bulk_corrections(corrections, source_file=filename)
        except Exception:
            pass

    # Store the schedule entries
    result = _store_schedule_entries(entries, filename, used_ocr=True)
    result['corrections_learned'] = corrections_stored
    result['filename'] = filename

    return jsonify(result)


@import_bp.route('/schedule/ocr-corrections', methods=['GET'])
def list_ocr_corrections():
    """GET /api/import/schedule/ocr-corrections - List learned OCR corrections."""
    field_type = request.args.get('field_type')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    try:
        from app.import_engine.ocr_learner import list_corrections, get_correction_stats
        result = list_corrections(field_type=field_type, page=page, per_page=per_page)
        result['stats'] = get_correction_stats()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@import_bp.route('/schedule/ocr-corrections', methods=['POST'])
def add_ocr_correction():
    """POST /api/import/schedule/ocr-corrections - Add a manual OCR correction.

    JSON body: {"ocr_text": "W1LLIAMS", "corrected_text": "WILLIAMS", "field_type": "patient_name"}
    """
    data = request.get_json(silent=True)
    if not data or 'ocr_text' not in data or 'corrected_text' not in data:
        return jsonify({'error': 'Provide ocr_text and corrected_text'}), 400

    try:
        from app.import_engine.ocr_learner import store_correction
        result = store_correction(
            ocr_text=data['ocr_text'],
            corrected_text=data['corrected_text'],
            field_type=data.get('field_type', 'patient_name'),
            source_file=data.get('source_file'),
        )
        if result:
            return jsonify({'stored': True, 'id': result.id})
        return jsonify({'stored': False, 'message': 'No correction needed (texts are identical)'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@import_bp.route('/schedule/ocr-corrections/<int:correction_id>', methods=['DELETE'])
def delete_ocr_correction(correction_id):
    """DELETE /api/import/schedule/ocr-corrections/<id> - Remove a learned correction."""
    from app.models import OcrCorrection
    correction = db.session.get(OcrCorrection, correction_id)
    if not correction:
        return jsonify({'error': 'Correction not found'}), 404
    db.session.delete(correction)
    db.session.commit()
    return jsonify({'deleted': correction_id})


@import_bp.route('/schedule/rematch', methods=['POST'])
def rematch_schedules():
    """POST /api/import/schedule/rematch - Re-run matching for unmatched entries.

    Useful after importing new billing records from Excel.
    """
    unmatched = ScheduleRecord.query.filter_by(match_status='UNMATCHED').all()
    matched_count = 0

    for entry in unmatched:
        billing_match = BillingRecord.query.filter_by(
            patient_name=entry.patient_name,
        )
        if entry.scheduled_date:
            billing_match = billing_match.filter_by(service_date=entry.scheduled_date)
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
