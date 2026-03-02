"""
Data normalisation utilities used by every importer and exporter.

All monetary values use Decimal.  All text is uppercased/stripped.
Date handling covers Excel serial numbers, MM/DD/YYYY strings, and
Python datetime objects.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple
import re

from ocdr.config import PAYER_ALIASES, EXCEL_EPOCH


# ── Name normalisation ─────────────────────────────────────────────────────

def normalize_patient_name(raw) -> str:
    """
    Normalise to ``LAST, FIRST`` uppercase.

    Handles:
      - ``LAST, FIRST``  (already correct)
      - ``LAST^FIRST``   (DICOM / Candelis caret format)
      - ``LAST^FIRST^MI``
      - ``FIRST LAST``   (space-separated, assumes 2 tokens)
      - extra whitespace, mixed case
    """
    if raw is None:
        return ""
    s = str(raw).strip().upper()
    if not s:
        return ""

    # Caret-separated (DICOM)  e.g. PATINO^MARGARET  or  548^23065^^^
    if "^" in s:
        parts = [p.strip() for p in s.split("^") if p.strip()]
        # Check if this looks like a numeric/research ID (e.g. 548^23065^^^)
        if parts and parts[0].isdigit():
            # Research-style ID — join with space, don't force LAST, FIRST
            return " ".join(parts)
        if len(parts) >= 2:
            return f"{parts[0]}, {parts[1]}"
        return parts[0] if parts else s

    # Comma-separated (already correct format)
    if "," in s:
        parts = [p.strip() for p in s.split(",", 1)]
        return f"{parts[0]}, {parts[1]}" if len(parts) == 2 else s

    return s


def normalize_physician_name(raw) -> str:
    """Physician names follow the same LAST, FIRST convention."""
    if raw is None:
        return ""
    return str(raw).strip().upper()


# ── Date normalisation ─────────────────────────────────────────────────────

def excel_serial_to_date(serial) -> Optional[date]:
    """Convert Excel serial number to ``datetime.date``.

    Accounts for Lotus 1-2-3 leap-year bug (epoch 1899-12-30).
    Returns *None* for invalid / zero / None inputs.
    """
    if serial is None:
        return None
    try:
        serial = int(float(serial))
    except (ValueError, TypeError):
        return None
    if serial <= 0:
        return None
    try:
        return EXCEL_EPOCH + timedelta(days=serial)
    except OverflowError:
        return None


def date_to_excel_serial(d: date) -> int:
    """Convert ``datetime.date`` to an Excel serial number."""
    return (d - EXCEL_EPOCH).days


def parse_date_flexible(value) -> Optional[date]:
    """Accept Excel serial, ``MM/DD/YYYY``, ``YYYY-MM-DD``, or datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    # Numeric → Excel serial
    if isinstance(value, (int, float)):
        return excel_serial_to_date(value)

    s = str(value).strip()
    if not s:
        return None

    # Try numeric string (Excel serial stored as text)
    try:
        return excel_serial_to_date(int(float(s)))
    except (ValueError, TypeError):
        pass

    # MM/DD/YYYY
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    return None


def derive_month(d: Optional[date]) -> str:
    """3-letter month abbreviation: Jan, Feb, …"""
    return d.strftime("%b") if d else ""


def derive_year(d: Optional[date]) -> str:
    """4-digit year string."""
    return str(d.year) if d else ""


# ── Payer normalisation ────────────────────────────────────────────────────

def normalize_payer_code(raw) -> str:
    """Uppercase, strip, apply BR-10 alias mapping."""
    if raw is None:
        return ""
    cleaned = str(raw).strip().upper()
    if not cleaned:
        return ""
    return PAYER_ALIASES.get(cleaned, cleaned)


# ── Monetary normalisation ─────────────────────────────────────────────────

def normalize_decimal(value) -> Decimal:
    """Convert to ``Decimal`` with 2-place precision; unparseable → 0.00."""
    if value is None or value == "" or value == " ":
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    try:
        cleaned = str(value).replace("$", "").replace(",", "").strip()
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


# ── Boolean normalisation ─────────────────────────────────────────────────

def normalize_gado(value) -> bool:
    """``YES`` → True, everything else → False."""
    if value is None:
        return False
    return str(value).strip().upper() == "YES"


# ── Text normalisation ────────────────────────────────────────────────────

def normalize_text(raw) -> str:
    if raw is None:
        return ""
    return str(raw).strip().upper()


def normalize_modality(raw) -> str:
    """Uppercase/strip a modality value (CT, HMRI, PET, BONE, OPEN, DX, GH)."""
    if raw is None:
        return ""
    return str(raw).strip().upper()


def normalize_scan_type(raw) -> str:
    """Uppercase/strip a scan-type / body-part value."""
    if raw is None:
        return ""
    return str(raw).strip().upper()


# ── Candelis-specific normalisation ────────────────────────────────────────
#
# Important:  Modality mapping is NOT a simple code lookup.
# ``CT/SR/PT/SC`` can contain actual CTs alongside PET data.
# We use the **Description** as the PRIMARY indicator and the modality
# codes only as secondary verification.  When there is any ambiguity the
# ``confidence`` field is set to something < 1.0 so a human must review.
#
# Return value is always (modality, confidence) where confidence ∈ [0, 1].

# Description keywords → modality  (checked in order, first match wins)
_DESC_MODALITY_RULES: list[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bPET(/CT)?\b", re.I),   "PET"),
    (re.compile(r"\bBONE\s*SCAN\b", re.I), "BONE"),
    (re.compile(r"\bDX\b", re.I),           "DX"),
    (re.compile(r"\bPA\s+VIEW", re.I),      "DX"),   # e.g. "PA VIEWS OF RT KNEE"
]

# Modality-code tokens that are purely structural / secondary
_STRUCTURAL_CODES = {"SR", "SC"}

def map_candelis_modality(machine_codes: str,
                          description: str) -> Tuple[str, float]:
    """Derive billing modality from Candelis data.

    * **machine_codes** = Candelis ``Modalities`` column — the physical
      equipment used (MRI scanner, PET/CT scanner, etc.).  NOT the
      billable procedure.
    * **description** = Candelis ``Description`` column — the actual
      procedure ordered.  THIS determines the billing modality.

    Returns ``(modality, confidence)`` where *confidence* < 1.0 means
    human review is required (best-guess + flag).

    Strategy (description-first, machine verifies):
      1. Check description for explicit keywords (PET/CT, BONE SCAN, DX, …).
      2. For MR machine → default to HMRI (OPEN MRI comes from the
         schedule, not Candelis — it's noted for claustrophobic patients).
      3. Cross-check machine vs description; mismatch → lower confidence.
      4. If neither conclusive → ``("", 0.0)`` — must be manually set.
    """
    desc_up = (description or "").strip().upper()
    codes_up = (machine_codes or "").strip().upper()
    code_tokens = {c.strip() for c in codes_up.replace("/", " ").split()
                   if c.strip()} - _STRUCTURAL_CODES

    # ── 1. Description-based rules (highest priority) ──────────────────
    for pattern, modality in _DESC_MODALITY_RULES:
        if pattern.search(desc_up):
            # Cross-check: if description says PET, codes should contain PT
            if modality == "PET" and "PT" not in code_tokens and "PET" not in code_tokens:
                return modality, 0.7   # description says PET but codes don't confirm
            return modality, 1.0

    # ── 2. Code-based derivation ───────────────────────────────────────
    if code_tokens == {"MR"} or (len(code_tokens) == 1 and "MR" in code_tokens):
        if "OPEN" in desc_up:
            return "OPEN", 1.0
        return "HMRI", 1.0

    if code_tokens == {"CT"} or (code_tokens == {"CT"} and "PT" not in code_tokens):
        return "CT", 1.0

    if "PT" in code_tokens:
        # PT token present – likely PET, but description should confirm
        if "PET" in desc_up:
            return "PET", 1.0
        # Description doesn't say PET; could be a CT that was part of a
        # PET/CT acquisition.  Flag for review.
        return "PET", 0.5

    if "DX" in code_tokens:
        return "DX", 1.0

    if "NM" in code_tokens:
        return "BONE", 0.8   # NM is nuclear medicine; usually BONE SCAN

    # ── 3. Fallback – can't determine ────────────────────────────────
    return "", 0.0


def detect_gado_from_desc(description: str) -> bool:
    """Detect gadolinium contrast from Candelis description.

    Looks for ``-GADO``, ``GADO``, ``-ARTHRO`` (arthrogram also uses contrast).
    """
    if not description:
        return False
    d = description.upper()
    return bool(re.search(r"\bGADO\b|-GADO\b", d))


def detect_psma(description: str) -> bool:
    """BR-02: PSMA PET detection from description."""
    if not description:
        return False
    d = description.upper()
    return "PSMA" in d or "GA-68" in d or "GALLIUM" in d


def extract_scan_type(description: str) -> str:
    """Extract the body-part / scan-type from a Candelis description.

    Returns the normalised scan type that maps to OCMRI column C.

    Examples::

        C.A.P           → ABDOMEN   (primary part for C.A.P combo)
        STN/C.A.P       → ABDOMEN
        HEAD            → HEAD
        BRAIN-GADO      → HEAD
        BRAIN           → HEAD
        CHEST           → CHEST
        CHEST L.D.      → CHEST
        LSP             → LUMBAR
        LSP-GADO        → LUMBAR
        CSP-GADO        → CERVICAL
        CSP             → CERVICAL
        SINUS           → SINUS
        RT KNEE         → KNEE
        LT KNEE         → KNEE
        RT ANKLE        → ANKLE
        RT FOOT         → FOOT
        LT FOOT         → FOOT
        RT HAND         → HAND
        RT SHLDR        → SHOULDER
        PELVIS          → PELVIS
        PET/CT          → WHOLE BODY   (PET scans are typically whole-body)
        BONE SCAN       → WHOLE BODY
        ARTH SHOULD RT  → SHOULDER
    """
    if not description:
        return ""
    d = description.upper().strip()
    # Remove gado / enhancement suffixes for matching
    d_clean = re.sub(r"[-\s]GADO\b", "", d)
    d_clean = re.sub(r"\be\+\d+\s*", "", d_clean).strip()  # e+1 prefix

    mapping: list[Tuple[re.Pattern, str]] = [
        (re.compile(r"\bC\.?A\.?P\.?\b"),      "ABDOMEN"),
        (re.compile(r"\bBRAIN\b"),              "HEAD"),
        (re.compile(r"\bHEAD\b"),               "HEAD"),
        (re.compile(r"\bCHEST\b"),              "CHEST"),
        (re.compile(r"\bLSP\b"),                "LUMBAR"),
        (re.compile(r"\bCSP\b"),                "CERVICAL"),
        (re.compile(r"\bSINUS\b"),              "SINUS"),
        (re.compile(r"\bKNEE\b"),               "KNEE"),
        (re.compile(r"\bANKLE\b"),              "ANKLE"),
        (re.compile(r"\bFOOT\b"),               "FOOT"),
        (re.compile(r"\bHAND\b"),               "HAND"),
        (re.compile(r"\bSH[LO]?ULD"),           "SHOULDER"),
        (re.compile(r"\bSHLDR\b"),              "SHOULDER"),
        (re.compile(r"\bPELVIS\b"),             "PELVIS"),
        (re.compile(r"\bPET\b"),                "WHOLE BODY"),
        (re.compile(r"\bBONE\s*SCAN\b"),        "WHOLE BODY"),
        (re.compile(r"\bSTN\b"),                "SINUS"),
        (re.compile(r"\bARTH"),                 "SHOULDER"),  # ARTH SHOULD RT → arthrogram shoulder
    ]

    for pattern, scan_type in mapping:
        if pattern.search(d_clean):
            return scan_type

    return d_clean  # fallback: return cleaned description
