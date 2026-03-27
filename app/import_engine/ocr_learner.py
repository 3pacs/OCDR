"""OCR Correction Learning for Handwritten Schedule Imports.

Stores user corrections when OCR misreads handwritten text,
and automatically applies learned corrections to future imports.

Works with the schedule_parser.py OCR pipeline:
  1. OCR extracts raw text from handwritten PDF
  2. This module applies any learned corrections to the raw text
  3. User reviews the result, submits corrections for mistakes
  4. Corrections are stored and applied to future imports

Fuzzy matching handles common handwriting OCR errors:
  - Character substitutions: 0↔O, 1↔I↔l, 5↔S, 8↔B
  - Missing/extra characters from sloppy handwriting
"""
from difflib import SequenceMatcher

from app.models import db, OcrCorrection


# Common OCR character confusions for handwritten text
_CHAR_SUBS = {
    '0': 'O', 'O': '0',
    '1': 'I', 'I': '1', 'l': '1',
    '5': 'S', 'S': '5',
    '8': 'B', 'B': '8',
    '6': 'G', 'G': '6',
    '2': 'Z', 'Z': '2',
    'D': '0', 'Q': 'O',
    'rn': 'm', 'cl': 'd',
}


def apply_learned_corrections(text, field_type="patient_name"):
    """Apply all learned corrections for a field type to the given text.

    Returns the corrected text. If no corrections apply, returns original.
    """
    if not text or not text.strip():
        return text

    text_upper = text.strip().upper()

    # Exact match lookup first (fastest)
    correction = OcrCorrection.query.filter_by(
        ocr_text=text_upper,
        field_type=field_type,
    ).first()

    if correction:
        correction.correction_count += 1
        db.session.commit()
        return correction.corrected_text

    # Fuzzy match: check all corrections for this field type
    # Only do this for patient_name (most error-prone) to keep fast
    if field_type == "patient_name":
        corrections = OcrCorrection.query.filter_by(field_type=field_type).all()
        best_match = None
        best_ratio = 0.0

        for corr in corrections:
            ratio = SequenceMatcher(None, text_upper, corr.ocr_text).ratio()
            if ratio > 0.85 and ratio > best_ratio:
                best_ratio = ratio
                best_match = corr

        if best_match:
            best_match.correction_count += 1
            db.session.commit()
            return best_match.corrected_text

    return text


def apply_corrections_to_entries(entries):
    """Apply learned corrections to a list of parsed schedule entries.

    Modifies entries in-place. Returns count of corrections applied.
    """
    corrections_applied = 0

    for entry in entries:
        # Correct patient name
        raw_name = entry.get('patient_name', '')
        if raw_name:
            corrected = apply_learned_corrections(raw_name, 'patient_name')
            if corrected != raw_name:
                entry['ocr_original_name'] = raw_name
                entry['patient_name'] = corrected
                corrections_applied += 1

        # Correct scan type
        raw_scan = entry.get('scan_type', '')
        if raw_scan:
            corrected = apply_learned_corrections(raw_scan, 'scan_type')
            if corrected != raw_scan:
                entry['scan_type'] = corrected
                corrections_applied += 1

        # Correct modality
        raw_mod = entry.get('modality', '')
        if raw_mod:
            corrected = apply_learned_corrections(raw_mod, 'modality')
            if corrected != raw_mod:
                entry['modality'] = corrected
                corrections_applied += 1

    return corrections_applied


def store_correction(ocr_text, corrected_text, field_type="patient_name", source_file=None):
    """Store a user correction for future OCR learning.

    If this exact OCR text → field_type pair already exists, updates the corrected text.
    """
    if not ocr_text or not corrected_text:
        return None

    ocr_text = ocr_text.strip().upper()
    corrected_text = corrected_text.strip().upper()

    if ocr_text == corrected_text:
        return None  # No correction needed

    existing = OcrCorrection.query.filter_by(
        ocr_text=ocr_text,
        field_type=field_type,
    ).first()

    if existing:
        existing.corrected_text = corrected_text
        existing.correction_count += 1
        db.session.commit()
        return existing

    correction = OcrCorrection(
        ocr_text=ocr_text,
        corrected_text=corrected_text,
        field_type=field_type,
        source_file=source_file,
    )
    db.session.add(correction)
    db.session.commit()
    return correction


def store_bulk_corrections(corrections, source_file=None):
    """Store multiple corrections at once.

    corrections: list of dicts with keys: ocr_text, corrected_text, field_type
    """
    stored = 0
    for corr in corrections:
        result = store_correction(
            ocr_text=corr.get('ocr_text', ''),
            corrected_text=corr.get('corrected_text', ''),
            field_type=corr.get('field_type', 'patient_name'),
            source_file=source_file,
        )
        if result:
            stored += 1
    return stored


def get_correction_stats():
    """Get summary stats for OCR corrections."""
    total = OcrCorrection.query.count()
    by_field = db.session.query(
        OcrCorrection.field_type,
        db.func.count(OcrCorrection.id),
        db.func.sum(OcrCorrection.correction_count),
    ).group_by(OcrCorrection.field_type).all()

    return {
        'total_corrections': total,
        'by_field': {
            row[0]: {'unique': row[1], 'total_applied': row[2] or 0}
            for row in by_field
        },
    }


def list_corrections(field_type=None, page=1, per_page=50):
    """List stored corrections with optional filtering."""
    per_page = min(per_page, 500)
    query = OcrCorrection.query

    if field_type:
        query = query.filter_by(field_type=field_type)

    query = query.order_by(OcrCorrection.correction_count.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return {
        'items': [{
            'id': c.id,
            'ocr_text': c.ocr_text,
            'corrected_text': c.corrected_text,
            'field_type': c.field_type,
            'correction_count': c.correction_count,
            'source_file': c.source_file,
        } for c in pagination.items],
        'total': pagination.total,
        'page': page,
        'pages': pagination.pages,
    }
