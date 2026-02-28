"""Shared validation and normalization for all import engines.

Centralizes date parsing, modality/carrier normalization, PSMA detection,
payment computation, and deduplication logic.
"""

from datetime import datetime, date, timedelta

from app.models import db, BillingRecord


# ── Excel serial date epoch ─────────────────────────────────────
EXCEL_EPOCH = datetime(1899, 12, 30)

# ── Modality normalization ──────────────────────────────────────
MODALITY_MAP = {
    "MRI": "HMRI", "HMRI": "HMRI", "HIGH FIELD MRI": "HMRI",
    "HIGH-FIELD MRI": "HMRI", "HF MRI": "HMRI",
    "CT": "CT", "CAT": "CT", "CAT SCAN": "CT",
    "PET": "PET", "PET/CT": "PET", "PET CT": "PET", "PETCT": "PET",
    "BONE": "BONE", "BONE DENSITY": "BONE", "DEXA": "BONE", "DXA": "BONE",
    "OPEN": "OPEN", "OPEN MRI": "OPEN",
    "DX": "DX", "X-RAY": "DX", "XRAY": "DX", "X RAY": "DX",
    "US": "US", "ULTRASOUND": "US", "SONO": "US",
    "NM": "NM", "NUCLEAR": "NM", "NUCLEAR MEDICINE": "NM",
}

# ── Insurance carrier normalization ─────────────────────────────
CARRIER_NORMALIZE = {
    "SELFPAY": "SELF PAY", "SELF-PAY": "SELF PAY",
    "SELF PAY": "SELF PAY", "CASH": "SELF PAY",
    "MEDICARE": "M/M", "MEDICAID": "M/M", "MEDI-CAL": "M/M",
    "MEDI CAL": "M/M",
}

# ── Date validation bounds ──────────────────────────────────────
MIN_VALID_DATE = date(1990, 1, 1)
MAX_VALID_DATE_OFFSET = timedelta(days=365)  # max 1 year in future


def parse_date(val):
    """Parse a date value from various formats (Excel serial, string, datetime).

    Returns None if the date is invalid, unparseable, or outside valid range.
    """
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val if _is_valid_date(val) else None
    if isinstance(val, datetime):
        d = val.date()
        return d if _is_valid_date(d) else None
    if isinstance(val, (int, float)):
        try:
            d = (EXCEL_EPOCH + timedelta(days=int(val))).date()
            return d if _is_valid_date(d) else None
        except (ValueError, OverflowError):
            return None
    val_str = str(val).strip()
    if not val_str:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y", "%Y%m%d"):
        try:
            d = datetime.strptime(val_str, fmt).date()
            if _is_valid_date(d):
                return d
        except ValueError:
            continue
    return None


def _is_valid_date(d):
    """Check if a date is within valid range."""
    today = date.today()
    return MIN_VALID_DATE <= d <= today + MAX_VALID_DATE_OFFSET


def parse_float(val):
    """Parse a float from string, removing currency symbols and commas."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = str(val).replace(",", "").replace("$", "").strip()
        result = float(cleaned) if cleaned else 0.0
        return max(result, 0.0)  # Payments should not be negative
    except (ValueError, TypeError):
        return 0.0


def parse_bool(val):
    """Parse boolean from Y/N/TRUE/FALSE/1/0."""
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    s = str(val).strip().upper()
    return s in ("Y", "YES", "TRUE", "1", "X", "GAD", "GADO")


def normalize_modality(val):
    """Normalize modality string to standard codes."""
    if not val:
        return "HMRI"
    upper = str(val).strip().upper()
    return MODALITY_MAP.get(upper, upper)


def normalize_carrier(val):
    """Normalize insurance carrier name."""
    if not val:
        return "UNKNOWN"
    upper = str(val).strip().upper()
    return CARRIER_NORMALIZE.get(upper, str(val).strip().upper())


def detect_psma(description, scan_type=None):
    """Detect PSMA scans from description or scan type (SM-11: expandable keywords)."""
    base_keywords = ("PSMA", "GA-68", "GA68", "GALLIUM", "PYLARIFY", "LOCAMETZ",
                     "ILLUCCIX", "DCFPyL", "18F-PSMA", "F-18 PSMA")
    # Merge with any learned keywords
    keywords = list(base_keywords)
    try:
        from app.models import NormalizationLearned
        learned = NormalizationLearned.query.filter_by(
            category="PSMA_KEYWORD", approved=True
        ).all()
        keywords.extend(n.raw_value.upper() for n in learned)
    except Exception:
        pass

    for val in (description, scan_type):
        if val:
            upper = str(val).upper()
            if any(kw in upper for kw in keywords):
                return True
    return False


def compute_total_payment(primary, secondary, total, extra=0.0):
    """Compute total_payment if not provided or if it's 0 but components exist.

    Logic: if total is 0 or None but primary/secondary exist, sum them up.
    """
    primary = primary or 0.0
    secondary = secondary or 0.0
    extra = extra or 0.0
    total = total or 0.0

    if total == 0.0 and (primary > 0 or secondary > 0):
        total = primary + secondary + extra
    return total


def build_dedup_set():
    """Load existing billing record dedup keys from the database.

    Returns a set of (patient_name, service_date, scan_type, modality) tuples.
    """
    existing = set()
    for rec in db.session.query(
        BillingRecord.patient_name, BillingRecord.service_date,
        BillingRecord.scan_type, BillingRecord.modality
    ).all():
        existing.add((rec.patient_name, rec.service_date, rec.scan_type, rec.modality))
    return existing


def is_duplicate(patient_name, service_date, scan_type, modality, dedup_set):
    """Check if a record already exists in the dedup set.

    Also adds the key to the set if not a duplicate (for batch checking).
    Returns True if duplicate.
    """
    key = (patient_name, service_date, scan_type, modality)
    if key in dedup_set:
        return True
    dedup_set.add(key)
    return False


def validate_billing_record(patient_name, service_date, referring_doctor=None,
                            scan_type=None, modality=None, insurance_carrier=None):
    """Validate required fields for a billing record.

    Returns (is_valid, errors) tuple.
    """
    errors = []
    if not patient_name or not str(patient_name).strip():
        errors.append("Missing patient name")
    if not service_date:
        errors.append("Missing or invalid service date")
    if not errors:
        return True, []
    return False, errors
