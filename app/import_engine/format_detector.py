"""Smart file format detection and routing engine.

Detects file type by extension, magic bytes, and content heuristics,
then routes to the appropriate parser. Handles:
  - Excel (.xlsx, .xls)
  - X12 835 EDI (.835, .edi, .txt with 835 content)
  - CSV (.csv, .txt with delimited data)
  - PDF (.pdf) — EOB remittance or schedule
  - Images (.png, .jpg, .tiff, .bmp) — scanned EOBs via OCR
"""
import os
import tempfile

from flask import request, jsonify
from app.import_engine import import_bp
from app.models import db


# Magic byte signatures for binary formats
MAGIC_BYTES = {
    b'PK\x03\x04': 'xlsx',      # ZIP archive (xlsx is a zip)
    b'%PDF': 'pdf',
    b'\x89PNG': 'image',
    b'\xff\xd8\xff': 'image',    # JPEG
    b'II\x2a\x00': 'image',     # TIFF little-endian
    b'MM\x00\x2a': 'image',     # TIFF big-endian
    b'BM': 'image',             # BMP
}

# Extension → format mapping (fallback after magic bytes)
EXT_MAP = {
    '.xlsx': 'xlsx', '.xls': 'xlsx',
    '.835': '835', '.edi': '835',
    '.csv': 'csv',
    '.pdf': 'pdf',
    '.txt': 'text',  # needs content sniffing
    '.png': 'image', '.jpg': 'image', '.jpeg': 'image',
    '.tiff': 'image', '.tif': 'image', '.bmp': 'image',
}


def detect_format(filepath, filename=None):
    """Detect the file format using magic bytes, extension, and content heuristics.

    Returns a dict with:
      - format: one of 'xlsx', '835', 'csv', 'pdf', 'eob_pdf', 'schedule_pdf', 'image', 'unknown'
      - confidence: float 0.0-1.0
      - details: human-readable description
    """
    if filename is None:
        filename = os.path.basename(filepath)
    ext = os.path.splitext(filename)[1].lower()

    # Step 1: Check magic bytes
    detected_magic = None
    try:
        with open(filepath, 'rb') as f:
            header = f.read(16)
        for sig, fmt in MAGIC_BYTES.items():
            if header[:len(sig)] == sig:
                detected_magic = fmt
                break
    except OSError:
        pass

    # Step 2: Extension-based detection
    detected_ext = EXT_MAP.get(ext, 'unknown')

    # Step 3: Content heuristic for text-based formats
    if detected_magic is None and detected_ext in ('text', '835', 'csv', 'unknown'):
        return _sniff_text_content(filepath, ext)

    # Step 4: For PDFs, sub-classify as EOB vs schedule
    if detected_magic == 'pdf' or detected_ext == 'pdf':
        return _classify_pdf(filepath)

    # Step 5: For images, always route to OCR
    if detected_magic == 'image' or detected_ext == 'image':
        return {
            'format': 'image',
            'confidence': 0.95 if detected_magic else 0.80,
            'details': f'Image file detected ({ext}), will process with OCR',
        }

    # Step 6: Excel
    if detected_magic == 'xlsx' or detected_ext == 'xlsx':
        return {
            'format': 'xlsx',
            'confidence': 0.99 if detected_magic else 0.90,
            'details': f'Excel workbook ({ext})',
        }

    return {'format': 'unknown', 'confidence': 0.0, 'details': f'Unrecognized format ({ext})'}


def _sniff_text_content(filepath, ext):
    """Sniff text file content to determine if it's 835, CSV, or other."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            preview = f.read(8000)
    except OSError:
        return {'format': 'unknown', 'confidence': 0.0, 'details': 'Cannot read file'}

    upper = preview.upper()

    # Check for X12 835 indicators
    edi_indicators = ('ISA*', 'BPR*', 'CLP*', 'ST*835')
    edi_matches = sum(1 for ind in edi_indicators if ind in upper)
    if edi_matches >= 2:
        return {
            'format': '835',
            'confidence': 0.95,
            'details': f'X12 835 EDI content detected in {ext} file ({edi_matches}/4 indicators)',
        }
    if edi_matches == 1:
        return {
            'format': '835',
            'confidence': 0.70,
            'details': f'Possible X12 835 content in {ext} file ({edi_matches}/4 indicators)',
        }

    # Check for CSV patterns (comma/tab/pipe delimited with consistent column count)
    lines = preview.split('\n')[:20]
    if len(lines) >= 2:
        for delim, name in [(',', 'comma'), ('\t', 'tab'), ('|', 'pipe')]:
            counts = [line.count(delim) for line in lines if line.strip()]
            if len(counts) >= 2 and counts[0] > 0 and len(set(counts)) <= 2:
                return {
                    'format': 'csv',
                    'confidence': 0.85,
                    'details': f'{name.title()}-delimited data detected ({counts[0]+1} columns)',
                    'delimiter': delim,
                }

    # Check for EOB-like text content (payment data patterns)
    eob_keywords = ('PAID', 'BILLED', 'CLAIM', 'CPT', 'PATIENT', 'AMOUNT', 'PAYMENT')
    eob_hits = sum(1 for kw in eob_keywords if kw in upper)
    if eob_hits >= 3:
        return {
            'format': 'eob_text',
            'confidence': 0.60,
            'details': f'Possible EOB text data ({eob_hits}/7 keywords matched)',
        }

    return {
        'format': 'unknown',
        'confidence': 0.10,
        'details': f'Plain text file, no recognizable format pattern',
    }


def _classify_pdf(filepath):
    """Sub-classify a PDF as EOB/remittance or schedule."""
    try:
        import pdfplumber
        with pdfplumber.open(filepath) as pdf:
            text = ''
            for page in pdf.pages[:3]:  # Check first 3 pages
                page_text = page.extract_text()
                if page_text:
                    text += page_text + '\n'
    except Exception:
        return {
            'format': 'pdf',
            'confidence': 0.50,
            'details': 'PDF file (could not extract text — may need OCR)',
        }

    if not text.strip():
        # Scanned PDF with no selectable text — needs OCR
        return {
            'format': 'scanned_pdf',
            'confidence': 0.80,
            'details': 'Scanned PDF with no selectable text — will process with OCR',
        }

    upper = text.upper()

    # Check for schedule patterns
    schedule_keywords = ('SCHEDULE', 'APPOINTMENT', 'APPT', 'ARRIVAL', 'EXAM TIME',
                         'PATIENT NAME', 'SCHEDULED', 'AM', 'PM', 'TECH')
    schedule_hits = sum(1 for kw in schedule_keywords if kw in upper)

    # Check for EOB/payment patterns
    eob_keywords = ('REMITTANCE', 'EXPLANATION OF BENEFITS', 'EOB', 'PAID AMOUNT',
                    'CLAIM NUMBER', 'CPT', 'SERVICE DATE', 'BILLED', 'ALLOWED',
                    'ADJUSTMENT', 'CHECK NUMBER', 'EFT', 'PAYER', 'PROVIDER')
    eob_hits = sum(1 for kw in eob_keywords if kw in upper)

    if schedule_hits >= 3 and schedule_hits > eob_hits:
        return {
            'format': 'schedule_pdf',
            'confidence': min(0.95, 0.50 + schedule_hits * 0.08),
            'details': f'Schedule PDF detected ({schedule_hits} schedule indicators)',
        }
    elif eob_hits >= 3:
        return {
            'format': 'eob_pdf',
            'confidence': min(0.95, 0.50 + eob_hits * 0.05),
            'details': f'EOB/Remittance PDF detected ({eob_hits} payment indicators)',
        }
    else:
        return {
            'format': 'pdf',
            'confidence': 0.40,
            'details': f'PDF file (schedule:{schedule_hits}, eob:{eob_hits} indicators — ambiguous)',
        }


def route_file(filepath, filename=None):
    """Detect format and import using the appropriate parser.

    Returns a dict with import results and format detection info.
    """
    detection = detect_format(filepath, filename)
    fmt = detection['format']

    result = {
        'filename': filename or os.path.basename(filepath),
        'detected_format': fmt,
        'detection_confidence': detection['confidence'],
        'detection_details': detection['details'],
    }

    try:
        if fmt == 'xlsx':
            from app.import_engine.excel_importer import import_excel
            import_result = import_excel(filepath)
            result.update(import_result)
            result['status'] = 'imported'

        elif fmt == '835':
            from app.parser.era_835_parser import parse_835_file
            import_result = parse_835_file(filepath)
            result.update(import_result)
            result['status'] = 'imported'

        elif fmt == 'csv':
            from app.import_engine.csv_importer import import_csv
            import_result = import_csv(filepath)
            result.update(import_result)
            result['status'] = 'imported'

        elif fmt in ('eob_pdf', 'pdf'):
            from app.import_engine.pdf_parser import parse_eob_pdf
            import_result = parse_eob_pdf(filepath)
            result.update(import_result)
            result['status'] = 'imported'

        elif fmt == 'schedule_pdf':
            from app.import_engine.schedule_parser import import_schedule_pdf
            import_result = import_schedule_pdf(filepath)
            result.update(import_result)
            result['status'] = 'imported'

        elif fmt == 'scanned_pdf':
            from app.import_engine.ocr_engine import ocr_pdf
            import_result = ocr_pdf(filepath)
            result.update(import_result)
            result['status'] = 'imported'

        elif fmt == 'image':
            from app.import_engine.ocr_engine import ocr_image
            import_result = ocr_image(filepath)
            result.update(import_result)
            result['status'] = 'imported'

        elif fmt == 'eob_text':
            from app.import_engine.pdf_parser import parse_eob_text
            import_result = parse_eob_text(filepath)
            result.update(import_result)
            result['status'] = 'imported'

        else:
            result['status'] = 'skipped'
            result['reason'] = f'Unrecognized format: {detection["details"]}'

    except Exception as e:
        result['status'] = 'error'
        result['reason'] = str(e)

    return result


@import_bp.route('/smart', methods=['POST'])
def smart_import():
    """POST /api/import/smart - AI-assisted smart import.

    Accepts any file, detects its format, and routes to the correct parser.
    Supports: Excel, 835 EDI, CSV, PDF (EOB/schedule), scanned images.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    # Save to temp file preserving extension
    ext = os.path.splitext(file.filename)[1]
    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    try:
        file.save(tmp_path)
        result = route_file(tmp_path, file.filename)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@import_bp.route('/detect', methods=['POST'])
def detect_file_format():
    """POST /api/import/detect - Detect file format without importing.

    Upload a file to see what format is detected and which parser would handle it.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    ext = os.path.splitext(file.filename)[1]
    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    try:
        file.save(tmp_path)
        detection = detect_format(tmp_path, file.filename)
        detection['filename'] = file.filename
        return jsonify(detection)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@import_bp.route('/smart-scan', methods=['POST'])
def smart_scan_directory():
    """POST /api/import/smart-scan - Smart scan a directory.

    Like eob-scan but handles ALL file types, not just 835.
    JSON body: { "folder_path": "X:\\EOBS" }
    """
    data = request.get_json(silent=True)
    if not data or 'folder_path' not in data:
        return jsonify({'error': 'Provide folder_path in JSON body'}), 400

    folder_path = data['folder_path']
    if not os.path.isdir(folder_path):
        return jsonify({'error': f'Folder not found: {folder_path}'}), 400

    # Collect all recognizable files
    all_extensions = set(EXT_MAP.keys())
    results = []

    for dirpath, _dirnames, filenames in os.walk(folder_path):
        for fname in sorted(filenames):
            ext = os.path.splitext(fname)[1].lower()
            if ext in all_extensions:
                fpath = os.path.join(dirpath, fname)
                result = route_file(fpath, fname)
                result['filename'] = os.path.relpath(fpath, folder_path)
                results.append(result)

    imported = [r for r in results if r.get('status') == 'imported']
    skipped = [r for r in results if r.get('status') == 'skipped']
    errors = [r for r in results if r.get('status') == 'error']

    # Group by detected format
    format_counts = {}
    for r in results:
        fmt = r.get('detected_format', 'unknown')
        format_counts[fmt] = format_counts.get(fmt, 0) + 1

    return jsonify({
        'folder': folder_path,
        'total_files_found': len(results),
        'files_imported': len(imported),
        'files_skipped': len(skipped),
        'files_errored': len(errors),
        'format_breakdown': format_counts,
        'details': results,
    })
