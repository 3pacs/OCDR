"""
Topaz Billing System Export Parser.

Parses extensionless .NET data export files from the Topaz billing server.
These files contain the authoritative chart_number ↔ topaz_id crosswalk
along with patient demographics and billing notes.

Supports auto-detection of common .NET export formats:
  - Pipe-delimited (|)
  - Tab-delimited (\\t)
  - Comma-delimited (CSV-like)
  - Fixed-width columns
  - XML / SOAP serialization

The parser sniffs file content to determine the format, auto-detects
headers via heuristic matching, and extracts crosswalk pairs plus any
additional patient/billing fields it can identify.
"""

import csv
import io
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)


# ─── Column name patterns for identifying crosswalk fields ──────────────

# Patterns that identify a chart number / patient ID column
CHART_NUMBER_PATTERNS = [
    "chart", "chart number", "chartnumber", "chart_number", "chart#",
    "chartno", "chart_no", "chart no",
    "patient id", "patient_id", "patientid", "patient #", "patient#",
    "mrn", "medical record", "record number", "record#",
    "account", "account number", "account#", "accountnumber", "acct",
    "pt id", "ptid", "pt_id",
]

# Patterns that identify a Topaz billing system ID column
TOPAZ_ID_PATTERNS = [
    "topaz", "topaz id", "topaz_id", "topazid", "topaz#",
    "billing id", "billing_id", "billingid", "billing#",
    "claim id", "claim_id", "claimid", "claim#", "claim number",
    "case id", "case_id", "caseid", "case#", "case number",
    "encounter", "encounter id", "encounter_id", "encounterid",
    "invoice", "invoice id", "invoice_id", "invoiceid", "invoice#",
    "transaction", "transaction id", "transaction_id", "trans id",
    "reference", "ref", "ref id", "ref#", "reference id", "refid",
    "ticket", "ticket#", "ticket id", "ticketid",
    "charge id", "charge_id", "chargeid",
]

# Patterns for patient name
PATIENT_NAME_PATTERNS = [
    "patient", "patient name", "patient_name", "patientname", "name",
    "pt name", "ptname", "pt_name", "client", "client name",
    "last name", "lastname", "last_name",  # partial — combine with first
]

# Patterns for service date
SERVICE_DATE_PATTERNS = [
    "date", "service date", "service_date", "servicedate", "dos",
    "date of service", "exam date", "visit date", "svc date",
]

# All known field pattern sets
FIELD_PATTERNS = {
    "chart_number": CHART_NUMBER_PATTERNS,
    "topaz_id": TOPAZ_ID_PATTERNS,
    "patient_name": PATIENT_NAME_PATTERNS,
    "service_date": SERVICE_DATE_PATTERNS,
}


@dataclass
class TopazExportResult:
    """Result from parsing a Topaz export file."""
    format_detected: str  # "pipe", "tab", "csv", "fixed", "xml", "unknown"
    total_rows: int = 0
    crosswalk_pairs: list[dict] = field(default_factory=list)
    # Each pair: {"chart_number": str, "topaz_id": str, "patient_name": str|None, ...}
    headers_found: list[str] = field(default_factory=list)
    column_mapping: dict[str, str] = field(default_factory=dict)
    # Maps our field names → detected column name
    extra_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_rows: list[dict] = field(default_factory=list)
    # All rows as dicts, for fields beyond crosswalk


# ─── Format detection ────────────────────────────────────────────────────

def _detect_format(content: str) -> str:
    """Sniff file content to determine the delimiter/format."""
    # Check for XML first
    stripped = content.strip()
    if stripped.startswith("<?xml") or stripped.startswith("<"):
        try:
            ET.fromstring(stripped[:10000] if len(stripped) > 10000 else stripped)
            return "xml"
        except ET.ParseError:
            # Might be partial XML or just starts with <
            if re.search(r"<[A-Za-z]+[\s>]", stripped[:500]):
                return "xml"

    # Sample first 20 non-empty lines
    lines = [l for l in content.split("\n") if l.strip()][:20]
    if not lines:
        return "unknown"

    # Count delimiters across sample lines
    pipe_counts = [l.count("|") for l in lines]
    tab_counts = [l.count("\t") for l in lines]
    comma_counts = [l.count(",") for l in lines]

    # A consistent delimiter count across lines suggests that format
    def _is_consistent(counts: list[int], min_count: int = 2) -> bool:
        nonzero = [c for c in counts if c >= min_count]
        if len(nonzero) < 3:
            return False
        # Most lines should have similar count
        from statistics import median
        med = median(nonzero)
        return sum(1 for c in nonzero if abs(c - med) <= 1) >= len(nonzero) * 0.7

    if _is_consistent(pipe_counts):
        return "pipe"
    if _is_consistent(tab_counts):
        return "tab"
    if _is_consistent(comma_counts):
        return "csv"

    # Fixed-width: lines are similar length, spaces but no consistent delimiters
    lengths = [len(l) for l in lines]
    if lengths and max(lengths) - min(lengths) < 10 and min(lengths) > 30:
        return "fixed"

    return "unknown"


def _match_column_name(header: str, field_patterns: dict[str, list[str]]) -> str | None:
    """Fuzzy-match a column header to a known field pattern.

    Checks all pattern sets and returns the field with the highest match score,
    avoiding false positives from partial overlaps like 'Patient Name' vs 'Patient ID'.
    """
    header_clean = header.lower().strip().replace("_", " ").replace("#", " ")

    # Pass 1: exact match (highest priority)
    for field_name, patterns in field_patterns.items():
        if header_clean in patterns:
            return field_name

    # Pass 2: fuzzy match — score against ALL fields, pick best
    best_field = None
    best_score = 0

    for field_name, patterns in field_patterns.items():
        match_result = process.extractOne(
            header_clean, patterns, scorer=fuzz.token_sort_ratio
        )
        if match_result:
            _, score, _ = match_result
            if score > best_score:
                best_score = score
                best_field = field_name

    return best_field if best_score >= 75 else None


# ─── Delimited file parsing ─────────────────────────────────────────────

def _parse_delimited(content: str, delimiter: str) -> TopazExportResult:
    """Parse pipe/tab/comma delimited content."""
    fmt_name = {"|": "pipe", "\t": "tab", ",": "csv"}.get(delimiter, "delimited")
    result = TopazExportResult(format_detected=fmt_name)

    lines = content.strip().split("\n")
    if not lines:
        result.warnings.append("Empty file")
        return result

    # Find header row — heuristic: first row where most cells are non-numeric text
    header_row_idx = 0
    best_text_ratio = 0

    for i, line in enumerate(lines[:10]):
        cells = [c.strip().strip('"') for c in line.split(delimiter)]
        if len(cells) < 2:
            continue
        text_cells = sum(1 for c in cells if c and not c.replace(".", "").replace("-", "").isdigit())
        ratio = text_cells / len(cells) if cells else 0
        if ratio > best_text_ratio:
            best_text_ratio = ratio
            header_row_idx = i

    header_line = lines[header_row_idx]
    headers = [h.strip().strip('"').strip() for h in header_line.split(delimiter)]
    result.headers_found = [h for h in headers if h]

    # Map headers to known fields — score all headers, assign best match per field
    header_scores = []  # [(field_name, col_index, score, header)]
    for i, header in enumerate(headers):
        if not header:
            continue
        header_clean = header.lower().strip().replace("_", " ").replace("#", " ")
        for field_name, patterns in FIELD_PATTERNS.items():
            if header_clean in patterns:
                header_scores.append((field_name, i, 1000, header))  # Exact = highest
            else:
                match_result = process.extractOne(header_clean, patterns, scorer=fuzz.token_sort_ratio)
                if match_result and match_result[1] >= 75:
                    header_scores.append((field_name, i, match_result[1], header))

    # Assign fields greedily: highest score first, no double-assignment
    header_scores.sort(key=lambda x: -x[2])
    col_mapping = {}
    claimed_cols = set()
    for field_name, col_idx, score, header in header_scores:
        if field_name not in col_mapping and col_idx not in claimed_cols:
            col_mapping[field_name] = col_idx
            result.column_mapping[field_name] = header
            claimed_cols.add(col_idx)

    if "chart_number" not in col_mapping and "topaz_id" not in col_mapping:
        result.warnings.append(
            f"Could not identify chart_number or topaz_id columns. "
            f"Headers found: {result.headers_found}"
        )

    # Parse data rows
    for line in lines[header_row_idx + 1:]:
        if not line.strip():
            continue

        cells = [c.strip().strip('"') for c in line.split(delimiter)]
        row_dict = {}

        for field_name, col_idx in col_mapping.items():
            if col_idx < len(cells):
                val = cells[col_idx].strip()
                if val:
                    row_dict[field_name] = val

        # Also capture all cells as a raw dict keyed by header
        raw = {}
        for i, cell in enumerate(cells):
            if i < len(headers) and headers[i]:
                raw[headers[i]] = cell.strip()
        result.raw_rows.append(raw)

        # Only add to crosswalk if we have at least one ID field
        if row_dict.get("chart_number") or row_dict.get("topaz_id"):
            result.crosswalk_pairs.append(row_dict)
            result.total_rows += 1

    # Track extra fields (headers we didn't map)
    mapped_indices = set(col_mapping.values())
    result.extra_fields = [h for i, h in enumerate(headers) if i not in mapped_indices and h]

    return result


# ─── XML parsing ─────────────────────────────────────────────────────────

def _parse_xml(content: str) -> TopazExportResult:
    """Parse XML/.NET serialized content."""
    result = TopazExportResult(format_detected="xml")

    try:
        # Handle .NET XML with namespace stripping
        content_clean = re.sub(r'\sxmlns[^"]*"[^"]*"', '', content)
        root = ET.fromstring(content_clean)
    except ET.ParseError as e:
        result.warnings.append(f"XML parse error: {e}")
        return result

    # Find repeating elements (rows) — the most common child tag
    tag_counts = {}
    for child in root.iter():
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        tag_counts[tag] = tag_counts.get(tag, 0) + 1

    # Find the tag that appears most and has children (row elements)
    row_tag = None
    max_count = 0
    for tag, count in tag_counts.items():
        if count > max_count and count > 1:
            # Check if elements with this tag have child elements or text
            for elem in root.iter(tag):
                if len(elem) > 0 or (elem.text and elem.text.strip()):
                    row_tag = tag
                    max_count = count
                    break

    if not row_tag:
        # Try DataTable format: look for Table or Row elements
        for candidate in ["Table", "Row", "Record", "Patient", "Claim", "Entry"]:
            found = list(root.iter(candidate))
            if len(found) > 1:
                row_tag = candidate
                break

    if not row_tag:
        result.warnings.append("Could not find repeating row elements in XML")
        return result

    # Extract field names from first row element
    sample_row = None
    for elem in root.iter(row_tag):
        if len(elem) > 0:
            sample_row = elem
            break

    if sample_row is None:
        result.warnings.append(f"Row elements <{row_tag}> have no children")
        return result

    # Map XML child tags to our fields
    xml_field_names = []
    col_mapping = {}
    for child in sample_row:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        xml_field_names.append(tag)
        field_name = _match_column_name(tag, FIELD_PATTERNS)
        if field_name:
            col_mapping[field_name] = tag
            result.column_mapping[field_name] = tag

    result.headers_found = xml_field_names

    if "chart_number" not in col_mapping and "topaz_id" not in col_mapping:
        result.warnings.append(
            f"Could not identify chart_number or topaz_id fields. "
            f"XML fields: {xml_field_names}"
        )

    # Parse all rows
    for elem in root.iter(row_tag):
        row_dict = {}
        raw = {}

        for child in elem:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            val = (child.text or "").strip()
            raw[tag] = val

            for field_name, xml_tag in col_mapping.items():
                if tag == xml_tag and val:
                    row_dict[field_name] = val

        result.raw_rows.append(raw)

        if row_dict.get("chart_number") or row_dict.get("topaz_id"):
            result.crosswalk_pairs.append(row_dict)
            result.total_rows += 1

    mapped_tags = set(col_mapping.values())
    result.extra_fields = [t for t in xml_field_names if t not in mapped_tags]

    return result


# ─── Fixed-width parsing ────────────────────────────────────────────────

def _parse_fixed_width(content: str) -> TopazExportResult:
    """Parse fixed-width column content by detecting column boundaries."""
    result = TopazExportResult(format_detected="fixed")

    lines = [l for l in content.split("\n") if l.strip()]
    if len(lines) < 2:
        result.warnings.append("Too few lines for fixed-width detection")
        return result

    # Detect column boundaries: positions where spaces appear in most lines
    line_len = max(len(l) for l in lines[:20])
    space_freq = [0] * (line_len + 1)
    for line in lines[:20]:
        for i, ch in enumerate(line):
            if ch == " ":
                space_freq[i] += 1

    # Columns start where space frequency drops (transition from high to low)
    threshold = len(lines[:20]) * 0.6
    in_gap = True
    boundaries = [0]
    for i in range(line_len):
        if space_freq[i] >= threshold:
            if not in_gap:
                boundaries.append(i)
                in_gap = True
        else:
            in_gap = False

    if len(boundaries) < 2:
        result.warnings.append("Could not detect column boundaries")
        return result

    # Extract headers from first line
    header_line = lines[0]
    headers = []
    for i in range(len(boundaries)):
        start = boundaries[i]
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(header_line)
        headers.append(header_line[start:end].strip())
    result.headers_found = [h for h in headers if h]

    # Map headers
    col_mapping = {}
    for i, header in enumerate(headers):
        if not header:
            continue
        field_name = _match_column_name(header, FIELD_PATTERNS)
        if field_name:
            col_mapping[field_name] = i
            result.column_mapping[field_name] = header

    # Parse data rows
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = []
        for i in range(len(boundaries)):
            start = boundaries[i]
            end = boundaries[i + 1] if i + 1 < len(boundaries) else len(line)
            cells.append(line[start:end].strip() if start < len(line) else "")

        row_dict = {}
        raw = {}
        for i, cell in enumerate(cells):
            if i < len(headers) and headers[i]:
                raw[headers[i]] = cell
            for field_name, col_idx in col_mapping.items():
                if col_idx == i and cell:
                    row_dict[field_name] = cell

        result.raw_rows.append(raw)
        if row_dict.get("chart_number") or row_dict.get("topaz_id"):
            result.crosswalk_pairs.append(row_dict)
            result.total_rows += 1

    return result


# ─── Main entry point ────────────────────────────────────────────────────

def parse_topaz_export(content: str, filename: str = "unknown") -> TopazExportResult:
    """
    Parse a Topaz billing system export file.

    Auto-detects format (pipe, tab, CSV, XML, fixed-width) and extracts
    chart_number ↔ topaz_id crosswalk pairs.

    Args:
        content: Raw file content as string
        filename: Original filename for logging

    Returns:
        TopazExportResult with crosswalk pairs and metadata
    """
    fmt = _detect_format(content)
    logger.info(f"Topaz export {filename}: detected format = {fmt}")

    if fmt == "pipe":
        result = _parse_delimited(content, "|")
    elif fmt == "tab":
        result = _parse_delimited(content, "\t")
    elif fmt == "csv":
        result = _parse_delimited(content, ",")
    elif fmt == "xml":
        result = _parse_xml(content)
    elif fmt == "fixed":
        result = _parse_fixed_width(content)
    else:
        # Try each delimiter and pick the one that produces the most crosswalk pairs
        best_result = None
        for delim, name in [("|", "pipe"), ("\t", "tab"), (",", "csv")]:
            try:
                candidate = _parse_delimited(content, delim)
                if best_result is None or candidate.total_rows > best_result.total_rows:
                    best_result = candidate
            except Exception:
                continue

        if best_result and best_result.total_rows > 0:
            result = best_result
            result.warnings.append(f"Format auto-detected by trial: {result.format_detected}")
        else:
            result = TopazExportResult(format_detected="unknown")
            result.warnings.append(
                "Could not determine file format. Expected pipe-delimited, "
                "tab-delimited, CSV, XML, or fixed-width."
            )

    logger.info(
        f"Topaz export {filename}: {result.total_rows} crosswalk pairs, "
        f"format={result.format_detected}, headers={result.headers_found[:10]}"
    )

    return result


def looks_like_topaz_export(content: str) -> bool:
    """
    Quick heuristic: does this content look like a Topaz/billing data export?

    Checks for presence of column headers that suggest chart/billing ID data.
    Used by the EOB scanner to decide whether to parse extensionless files.
    """
    # Check first 2000 chars for header-like patterns
    sample = content[:2000].lower()

    billing_keywords = [
        "chart", "patient", "billing", "account", "topaz",
        "claim", "encounter", "invoice", "mrn", "record",
        "charge", "reference", "transaction",
    ]

    id_keywords = [
        "id", "number", "#", "no", "num",
    ]

    has_billing = any(kw in sample for kw in billing_keywords)
    has_id = any(kw in sample for kw in id_keywords)

    # Also check for structured data patterns (delimiters or XML)
    has_structure = (
        sample.count("|") > 5 or
        sample.count("\t") > 5 or
        "<" in sample[:100] or
        sample.count(",") > 10
    )

    return has_billing and (has_id or has_structure)
