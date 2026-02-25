"""Schedule text parser — extracts structured appointment data from OCR text.

Handles common radiology schedule formats:
  - Table-based layouts (columns: Time, Patient, MRN, DOB, Modality, etc.)
  - Line-per-appointment formats
  - Date headers followed by appointment blocks

Returns list of dicts with whatever fields could be extracted.
"""

import re
import logging
from datetime import datetime

log = logging.getLogger(__name__)

# Common date patterns in schedule PDFs
DATE_PATTERNS = [
    r'(\d{1,2}/\d{1,2}/\d{2,4})',          # 1/15/2025 or 01/15/25
    r'(\d{4}-\d{2}-\d{2})',                  # 2025-01-15
    r'([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})',   # January 15, 2025
]

TIME_PATTERN = r'(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)'

# Common modality abbreviations
MODALITIES = {'CT', 'MRI', 'HMRI', 'PET', 'XRAY', 'DX', 'US', 'BONE',
              'OPEN', 'DEXA', 'FLUORO', 'MAMMO', 'NM', 'ULTRASOUND',
              'MR', 'CR', 'DR', 'PT', 'NUC'}

# MRN / patient ID patterns
MRN_PATTERN = r'\b(?:MRN|ID|PT)?[#:]?\s*(\d{4,10})\b'

# DOB pattern
DOB_PATTERN = r'(?:DOB|D\.O\.B\.?|BIRTH)\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4})'


def parse_schedule_text(text, source_date=None):
    """Parse raw OCR text into a list of appointment entries.

    Each entry is a dict with available fields:
      patient_name, patient_id, birth_date, time_slot, modality,
      scan_type, referring_doctor, schedule_date, insurance_carrier
    """
    if not text or len(text.strip()) < 10:
        return []

    entries = []
    lines = text.split('\n')

    # Try to find a date header for the page
    page_date = source_date
    for line in lines[:5]:
        d = _extract_date(line)
        if d:
            page_date = d
            break

    # Strategy 1: Look for structured lines with multiple fields
    for line in lines:
        line = line.strip()
        if len(line) < 10:
            continue

        entry = _parse_appointment_line(line, page_date)
        if entry and entry.get('patient_name'):
            entries.append(entry)

    return entries


def parse_schedule_table(table_rows, source_date=None):
    """Parse a pdfplumber-extracted table into appointment entries.

    table_rows: list of lists (first row is usually headers)
    """
    if not table_rows or len(table_rows) < 2:
        return []

    # Try to identify column roles from header row
    headers = [str(h).strip().upper() if h else '' for h in table_rows[0]]
    col_map = _map_columns(headers)

    if not col_map:
        return []

    entries = []
    for row in table_rows[1:]:
        if not row or all(c is None or str(c).strip() == '' for c in row):
            continue

        entry = {}
        for field, idx in col_map.items():
            if idx < len(row) and row[idx]:
                val = str(row[idx]).strip()
                if val:
                    entry[field] = val

        # Parse date fields
        if 'birth_date' in entry:
            entry['birth_date'] = _extract_date(entry['birth_date'])
        if 'schedule_date' in entry:
            entry['schedule_date'] = _extract_date(entry['schedule_date'])
        elif source_date:
            entry['schedule_date'] = source_date

        if entry.get('patient_name'):
            entries.append(entry)

    return entries


def _map_columns(headers):
    """Map header names to our field names.  Returns {field: col_index}."""
    mapping = {}
    keywords = {
        'patient_name':     ['PATIENT', 'NAME', 'PATIENT NAME', 'PAT NAME', 'PT NAME', 'PATIENT_NAME'],
        'patient_id':       ['MRN', 'PATIENT ID', 'ID', 'PT ID', 'PAT ID', 'PATIENT_ID', 'CHART'],
        'birth_date':       ['DOB', 'BIRTH', 'DATE OF BIRTH', 'BIRTHDATE', 'D.O.B'],
        'time_slot':        ['TIME', 'APPT TIME', 'SCHEDULED', 'APPT', 'START'],
        'modality':         ['MODALITY', 'MOD', 'EXAM TYPE', 'TYPE'],
        'scan_type':        ['EXAM', 'PROCEDURE', 'DESCRIPTION', 'STUDY', 'EXAM DESC'],
        'referring_doctor':  ['REFERRING', 'REF DR', 'REF PHYSICIAN', 'DOCTOR', 'PHYSICIAN', 'REF MD', 'ORDERING'],
        'insurance_carrier': ['INSURANCE', 'PAYER', 'INS', 'CARRIER', 'PLAN'],
        'schedule_date':    ['DATE', 'EXAM DATE', 'APPT DATE', 'SERVICE DATE', 'SCHED DATE'],
        'jacket_number':    ['JACKET', 'JACKET #', 'JACKET NO'],
        'notes':            ['NOTES', 'COMMENTS', 'NOTE'],
    }

    for field, kws in keywords.items():
        for i, h in enumerate(headers):
            if h in kws or any(kw in h for kw in kws):
                mapping[field] = i
                break

    return mapping


def _parse_appointment_line(line, page_date=None):
    """Try to extract appointment fields from a single text line."""
    entry = {}

    # Time
    time_match = re.search(TIME_PATTERN, line)
    if time_match:
        entry['time_slot'] = time_match.group(1)

    # MRN
    mrn_match = re.search(MRN_PATTERN, line)
    if mrn_match:
        entry['patient_id'] = mrn_match.group(1)

    # DOB
    dob_match = re.search(DOB_PATTERN, line, re.IGNORECASE)
    if dob_match:
        entry['birth_date'] = _extract_date(dob_match.group(1))

    # Modality
    for mod in MODALITIES:
        if re.search(r'\b' + mod + r'\b', line, re.IGNORECASE):
            entry['modality'] = mod
            break

    # Try to extract patient name — usually the longest capitalized word sequence
    # that isn't a known keyword
    name = _extract_name(line)
    if name:
        entry['patient_name'] = name

    if page_date:
        entry['schedule_date'] = page_date

    # Only return if we got at least a name or MRN
    if entry.get('patient_name') or entry.get('patient_id'):
        return entry
    return None


def _extract_name(line):
    """Try to pull a patient name from a line of text.

    Looks for LAST, FIRST or LAST FIRST patterns with capital letters.
    """
    # Pattern: LASTNAME, FIRSTNAME or LASTNAME,FIRSTNAME
    match = re.search(r'([A-Z][A-Z\'-]+),\s*([A-Z][A-Za-z\'-]+)', line)
    if match:
        return f"{match.group(1)}, {match.group(2)}"

    # Pattern: multiple capitalized words (at least 2 words, each 2+ chars)
    words = re.findall(r'\b([A-Z][A-Za-z\'-]{1,})\b', line)
    # Filter out modalities and common keywords
    skip = MODALITIES | {'THE', 'FOR', 'AND', 'WITH', 'FROM', 'DATE',
                         'TIME', 'MRN', 'DOB', 'REF', 'INS', 'EXAM',
                         'PATIENT', 'DOCTOR', 'PHYSICIAN', 'INSURANCE'}
    name_words = [w for w in words if w.upper() not in skip]
    if len(name_words) >= 2:
        return ' '.join(name_words[:3])

    return None


def _extract_date(text):
    """Extract a date from text, return as date object or None."""
    if not text:
        return None
    text = str(text).strip()

    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            date_str = match.group(1)
            for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%B %d, %Y', '%B %d %Y'):
                try:
                    return datetime.strptime(date_str.replace(',', ''), fmt).date()
                except ValueError:
                    continue
    return None
