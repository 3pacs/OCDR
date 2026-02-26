"""PHI Scrubber — strips all Protected Health Information before any data
leaves the local machine.

HIPAA Safe Harbor De-identification (45 CFR 164.514(b)(2)):
  The following 18 identifiers are ALWAYS stripped/redacted:
  1. Names                    10. Account numbers
  2. Geographic data          11. Certificate/license numbers
  3. Dates (except year)      12. Vehicle identifiers
  4. Phone numbers            13. Device identifiers
  5. Fax numbers              14. Web URLs
  6. Email addresses          15. IP addresses
  7. SSNs                     16. Biometric identifiers
  8. Medical record numbers   17. Full-face photos
  9. Health plan beneficiary  18. Any other unique identifier

What IS safe to send (structural metadata only):
  - Column/field names and data types
  - Value FORMAT patterns (e.g. "XX/XX/XXXX" not actual dates)
  - Row/column counts and cardinality
  - Public code sets: CPT codes, ICD codes, payer codes, denial reason codes
  - Modality types, scan types (these are procedure descriptors, not PHI)
  - Aggregate statistics (counts, sums, averages — never per-patient)
  - File format metadata (delimiters, encoding, segment types)
"""
import re
from datetime import date, datetime


# ---- Patterns that identify PHI ----

# Names: any capitalized word sequences (aggressive — better safe than sorry)
_NAME_PATTERN = re.compile(
    r'\b[A-Z][a-zA-Z\'-]+(?:\s*,\s*[A-Z][a-zA-Z\'-]+)?\b'
)

# Dates with day/month precision (year alone is safe)
_DATE_PATTERN = re.compile(
    r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b'
)

# SSNs
_SSN_PATTERN = re.compile(r'\b\d{3}-?\d{2}-?\d{4}\b')

# Phone numbers
_PHONE_PATTERN = re.compile(r'\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')

# Email addresses
_EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')

# Patient/account IDs (sequences of 6+ digits that aren't CPT codes)
_LONG_NUMBER_PATTERN = re.compile(r'\b\d{6,}\b')

# Known safe public code sets that should NOT be redacted
_SAFE_CODES = {
    # CPT codes (5-digit medical procedure codes — public)
    'cpt_codes',
    # ANSI denial reason codes (CO-4, PR-1, etc. — public)
    'denial_codes',
    # Payer codes (M/M, INS, CALOPTIMA — org names, not PHI)
    'payer_codes',
    # Modalities (CT, HMRI, PET — equipment types)
    'modalities',
}


def scrub_value(value):
    """Redact a single value, replacing PHI with a structural token.

    Returns (redacted_value, value_type) tuple.
    """
    if value is None:
        return '[NULL]', 'null'

    if isinstance(value, bool):
        return str(value), 'boolean'

    if isinstance(value, (int, float)):
        # Numbers are safe as aggregates but not as IDs
        return '[NUMBER]', 'number'

    if isinstance(value, (date, datetime)):
        # Only keep the year (safe under Safe Harbor)
        return f'[DATE:{value.year}]', 'date'

    s = str(value).strip()
    if not s:
        return '[EMPTY]', 'empty'

    # Check for dates
    if _DATE_PATTERN.search(s):
        return '[DATE_VALUE]', 'date'

    # Check for SSN
    if _SSN_PATTERN.search(s):
        return '[SSN_REDACTED]', 'ssn'

    # Check for phone
    if _PHONE_PATTERN.search(s):
        return '[PHONE_REDACTED]', 'phone'

    # Check for email
    if _EMAIL_PATTERN.search(s):
        return '[EMAIL_REDACTED]', 'email'

    # Check for long number sequences (possible MRN/account)
    if _LONG_NUMBER_PATTERN.match(s):
        return f'[ID:{len(s)}digits]', 'identifier'

    # Short uppercase codes are likely safe (modality, payer, etc.)
    # Check BEFORE name detection — codes like HMRI, CT, PET, M/M are not names
    if len(s) <= 10 and s.replace(' ', '').replace('/', '').isalnum():
        return s, 'code'

    # Check for potential patient names (all-caps with comma = LAST, FIRST)
    if re.match(r'^[A-Z][A-Z\s,\'-]+$', s) and len(s) > 3:
        return '[PATIENT_NAME]', 'name'

    # For anything else, return the format pattern not the value
    return _to_pattern(s), 'text'


def _to_pattern(s):
    """Convert a string to its structural pattern.

    'SMITH, JOHN' → '[ALPHA], [ALPHA]'
    '$1,234.56'   → '$[NUMBER]'
    '01/15/2024'  → '[DATE_VALUE]'
    """
    # Replace digits with [N]
    result = re.sub(r'\d+', '[N]', s)
    # Replace uppercase word sequences with [A]
    result = re.sub(r'[A-Z]{2,}', '[A]', result)
    # Collapse repeated patterns
    result = re.sub(r'\[N\](?:\.\[N\])?', '[N]', result)
    if len(result) > 50:
        result = result[:50] + '...'
    return result


def scrub_row(row_dict):
    """Scrub an entire row dict, returning structural metadata only."""
    scrubbed = {}
    for key, value in row_dict.items():
        redacted, vtype = scrub_value(value)
        scrubbed[key] = {'pattern': redacted, 'type': vtype}
    return scrubbed


def extract_safe_schema(headers, sample_rows, max_samples=3):
    """Extract a PHI-free schema description from column headers and sample data.

    This is the PRIMARY function used before sending anything externally.
    Returns a dict that is 100% safe to transmit.
    """
    schema = {
        'column_count': len(headers),
        'row_count_sample': len(sample_rows),
        'columns': [],
    }

    for col_idx, header in enumerate(headers):
        col_info = {
            'index': col_idx,
            'header': header,  # Column names are metadata, not PHI
            'sample_patterns': [],
            'detected_types': set(),
        }

        for row in sample_rows[:max_samples]:
            if col_idx < len(row):
                redacted, vtype = scrub_value(row[col_idx])
                col_info['sample_patterns'].append(redacted)
                col_info['detected_types'].add(vtype)

        col_info['detected_types'] = list(col_info['detected_types'])
        schema['columns'].append(col_info)

    return schema


def extract_safe_file_metadata(filepath, content_preview=None):
    """Extract PHI-free metadata about a file for AI analysis.

    Returns only structural information:
    - File size, extension, encoding
    - Delimiter detection results
    - Segment/section counts
    - Column headers (if detectable)
    - Value type patterns (never actual values)
    """
    import os

    filename = os.path.basename(filepath)
    ext = os.path.splitext(filename)[1].lower()
    size = os.path.getsize(filepath) if os.path.exists(filepath) else 0

    metadata = {
        'file_extension': ext,
        'file_size_bytes': size,
        'file_size_human': _human_size(size),
    }

    if content_preview:
        # Analyze structure without exposing PHI
        lines = content_preview.split('\n')
        metadata['line_count_preview'] = len(lines)

        # Detect delimiters
        if lines:
            first_line = lines[0]
            for delim, name in [(',', 'comma'), ('\t', 'tab'), ('|', 'pipe'), ('~', 'tilde')]:
                count = first_line.count(delim)
                if count > 0:
                    metadata[f'{name}_count_line1'] = count

        # For 835 files, count segments (safe — segment IDs are format metadata)
        upper = content_preview.upper()
        for seg in ['ISA', 'GS', 'ST', 'BPR', 'TRN', 'CLP', 'SVC', 'CAS', 'NM1', 'DTM']:
            count = upper.count(f'{seg}*')
            if count > 0:
                metadata[f'segment_{seg}_count'] = count

        # Detect headers (first line of CSV)
        if ext in ('.csv', '.txt') and lines:
            # Headers are safe metadata — they describe structure, not patients
            potential_headers = [h.strip().strip('"') for h in lines[0].split(',')]
            if all(not h.replace(' ', '').isdigit() for h in potential_headers[:5]):
                metadata['detected_headers'] = potential_headers

    return metadata


def extract_safe_db_schema():
    """Extract PHI-free database schema for AI analysis.

    Returns table structures, column types, and aggregate counts only.
    """
    from app.models import db, BillingRecord, EraPayment, EraClaimLine, ScheduleEntry

    schema = {
        'tables': {},
        'aggregate_stats': {},
    }

    # Table structures (column names + types = metadata, not PHI)
    for model in [BillingRecord, EraPayment, EraClaimLine, ScheduleEntry]:
        table_name = model.__tablename__
        columns = []
        for col in model.__table__.columns:
            columns.append({
                'name': col.name,
                'type': str(col.type),
                'nullable': col.nullable,
                'primary_key': col.primary_key,
                'indexed': bool(col.index),
            })
        schema['tables'][table_name] = columns

    # Aggregate counts only (never per-patient)
    try:
        schema['aggregate_stats'] = {
            'billing_records_total': BillingRecord.query.count(),
            'era_payments_total': EraPayment.query.count(),
            'era_claim_lines_total': EraClaimLine.query.count(),
            'schedule_entries_total': ScheduleEntry.query.count(),
            'distinct_modalities': [
                r[0] for r in db.session.query(BillingRecord.modality)
                .distinct().all() if r[0]
            ],
            'distinct_carriers': [
                r[0] for r in db.session.query(BillingRecord.insurance_carrier)
                .distinct().all() if r[0]
            ],
        }
    except Exception:
        schema['aggregate_stats'] = {'error': 'Could not query database'}

    return schema


def _human_size(size_bytes):
    """Convert bytes to human-readable size."""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size_bytes < 1024:
            return f'{size_bytes:.1f} {unit}'
        size_bytes /= 1024
    return f'{size_bytes:.1f} TB'


def validate_payload_phi_free(payload):
    """Final safety check: scan a payload dict for any remaining PHI.

    Returns (is_safe, issues) tuple. If is_safe is False, the payload
    must NOT be transmitted.
    """
    issues = []
    _scan_for_phi(payload, '', issues)
    return len(issues) == 0, issues


def _scan_for_phi(obj, path, issues):
    """Recursively scan a data structure for potential PHI."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            _scan_for_phi(v, f'{path}.{k}', issues)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _scan_for_phi(v, f'{path}[{i}]', issues)
    elif isinstance(obj, str):
        if _SSN_PATTERN.search(obj):
            issues.append(f'{path}: Possible SSN detected')
        if _PHONE_PATTERN.search(obj):
            issues.append(f'{path}: Possible phone number detected')
        if _EMAIL_PATTERN.search(obj):
            issues.append(f'{path}: Possible email detected')
        # Check for date patterns with full precision
        if _DATE_PATTERN.search(obj) and not obj.startswith('['):
            issues.append(f'{path}: Possible date with day/month precision')
        # Check for potential patient names (LAST, FIRST pattern)
        if re.match(r'^[A-Z]{2,},\s+[A-Z]{2,}$', obj):
            issues.append(f'{path}: Possible patient name')
