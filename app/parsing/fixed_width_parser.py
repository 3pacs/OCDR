"""
Fixed-Width Record Parser for .NET Server Export Files.

Parses extensionless files that use fixed-width binary record format,
common in .NET/VB6/COBOL legacy billing systems (e.g., Topaz server).

Format characteristics:
  - Each record is exactly N bytes (typically 128 = 126 data + 2 CRLF)
  - No header row — field positions are discovered by analyzing data patterns
  - Records may contain patient names, IDs, dates, notes, etc.
  - Field positions are consistent across all records in a file

Discovery strategy:
  1. Detect record width by finding the most common line length, or by
     checking if file size is evenly divisible by candidate widths
  2. Analyze character patterns across many records to find field boundaries
     (transitions between numeric/alpha/space zones)
  3. Classify each field zone: numeric ID, patient name, date, text note, etc.
  4. Cross-reference discovered IDs against known billing record IDs
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime

logger = logging.getLogger(__name__)

# Common record widths in .NET/legacy systems
CANDIDATE_WIDTHS = [128, 132, 64, 80, 100, 160, 200, 256, 512]

# US state abbreviations for auto-detection
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "VI", "GU", "AS", "MP",
}

# Patterns for content-based field detection
_RE_PHONE = re.compile(r"^\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}$")
_RE_ZIP = re.compile(r"^\d{5}(-\d{4})?$")
_RE_DATE = re.compile(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}")
_RE_DATE_ISO = re.compile(r"\d{4}[/\-]\d{2}[/\-]\d{2}")
_RE_DATE_COMPACT = re.compile(r"^\d{8}$")
_RE_INSURANCE = re.compile(r"^[A-Z]{1,3}\d{6,12}$|^\d{9,15}$")


@dataclass
class FieldZone:
    """A detected field within a fixed-width record."""
    start: int
    end: int
    width: int
    field_type: str  # "numeric", "alpha", "date", "mixed", "padding"
    label: str = ""  # Assigned label like "id_1", "name_1", "date_1"
    sample_values: list[str] = field(default_factory=list)


@dataclass
class FixedWidthResult:
    """Result from parsing a fixed-width record file."""
    record_width: int = 0
    total_records: int = 0
    field_zones: list[dict] = field(default_factory=list)
    records: list[dict] = field(default_factory=list)
    # Each record is a dict of {field_label: value}
    id_fields: list[str] = field(default_factory=list)
    # Field labels that look like patient/billing IDs
    name_fields: list[str] = field(default_factory=list)
    # Field labels that look like patient names
    date_fields: list[str] = field(default_factory=list)
    # Field labels that look like dates
    phone_fields: list[str] = field(default_factory=list)
    zip_fields: list[str] = field(default_factory=list)
    state_fields: list[str] = field(default_factory=list)
    city_fields: list[str] = field(default_factory=list)
    insurance_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    format_info: str = ""


def detect_record_width(content: bytes | str) -> int | None:
    """
    Detect the fixed record width of a file.

    Strategy:
    1. If content has consistent line lengths (CRLF or LF delimited), use that
    2. If file size is evenly divisible by a candidate width, use that
    3. Return None if no consistent width detected
    """
    if isinstance(content, str):
        raw = content.encode("utf-8", errors="replace")
    else:
        raw = content

    file_size = len(raw)

    # Strategy 1: Check for CRLF-delimited records with consistent length
    if b"\r\n" in raw[:1000]:
        lines = raw.split(b"\r\n")
        # Remove empty trailing element
        if lines and not lines[-1]:
            lines = lines[:-1]
        if len(lines) >= 10:
            # Count line lengths (including the 2-byte CRLF)
            lengths = {}
            for line in lines[:500]:
                ll = len(line)
                if ll > 0:
                    lengths[ll] = lengths.get(ll, 0) + 1
            if lengths:
                most_common_len = max(lengths, key=lengths.get)
                count = lengths[most_common_len]
                # If >80% of lines have the same length, that's our record width
                total_lines = sum(lengths.values())
                if count / total_lines >= 0.8:
                    # Record width = data bytes + 2 (CRLF)
                    return most_common_len + 2

    # Strategy 1b: Check for LF-delimited
    if b"\n" in raw[:1000]:
        lines = raw.split(b"\n")
        if lines and not lines[-1]:
            lines = lines[:-1]
        if len(lines) >= 10:
            lengths = {}
            for line in lines[:500]:
                ll = len(line)
                if ll > 0:
                    # Strip trailing \r if present
                    if line.endswith(b"\r"):
                        ll -= 1
                    lengths[ll] = lengths.get(ll, 0) + 1
            if lengths:
                most_common_len = max(lengths, key=lengths.get)
                count = lengths[most_common_len]
                total_lines = sum(lengths.values())
                if count / total_lines >= 0.8:
                    return most_common_len + 2  # Assume CRLF canonical width

    # Strategy 2: Check file size divisibility by candidate widths
    for width in CANDIDATE_WIDTHS:
        if file_size >= width * 10 and file_size % width == 0:
            record_count = file_size // width
            if record_count >= 10:
                return width

    return None


def _split_into_records(content: bytes | str, record_width: int) -> list[str]:
    """Split content into fixed-width records, handling CRLF."""
    if isinstance(content, str):
        raw = content.encode("utf-8", errors="replace")
    else:
        raw = content

    records = []

    # Try CRLF-split first (most common for .NET exports)
    if b"\r\n" in raw[:record_width * 2]:
        lines = raw.split(b"\r\n")
        data_width = record_width - 2
        for line in lines:
            if len(line) == 0:
                continue
            try:
                text = line[:data_width].decode("utf-8", errors="replace")
                records.append(text)
            except Exception:
                continue
    else:
        # No line endings — read as raw byte blocks
        data_width = record_width
        for offset in range(0, len(raw), record_width):
            block = raw[offset:offset + record_width]
            if len(block) < record_width // 2:
                break
            try:
                text = block.rstrip(b"\r\n\x00").decode("utf-8", errors="replace")
                records.append(text)
            except Exception:
                continue

    return records


def _analyze_field_zones(records: list[str], data_width: int) -> list[FieldZone]:
    """
    Analyze character patterns across records to discover field boundaries.

    For each byte position, classifies it as: digit, alpha, space, or other.
    Transitions between zones indicate field boundaries.
    """
    if not records:
        return []

    sample_size = min(len(records), 500)
    sample = records[:sample_size]

    # For each position, count character types
    pos_types = []
    for pos in range(data_width):
        counts = {"digit": 0, "alpha": 0, "space": 0, "other": 0}
        for rec in sample:
            if pos < len(rec):
                ch = rec[pos]
                if ch.isdigit():
                    counts["digit"] += 1
                elif ch.isalpha():
                    counts["alpha"] += 1
                elif ch == " ":
                    counts["space"] += 1
                else:
                    counts["other"] += 1
            else:
                counts["space"] += 1
        # Determine dominant type for this position
        total = sum(counts.values())
        if total == 0:
            pos_types.append("space")
        elif counts["space"] / total > 0.9:
            pos_types.append("space")
        elif counts["digit"] / total > 0.5:
            pos_types.append("digit")
        elif counts["alpha"] / total > 0.5:
            pos_types.append("alpha")
        elif (counts["alpha"] + counts["space"]) / total > 0.7:
            pos_types.append("alpha")
        elif (counts["digit"] + counts["space"]) / total > 0.7:
            pos_types.append("digit")
        else:
            pos_types.append("mixed")

    # Merge consecutive positions of the same type into zones
    zones = []
    if not pos_types:
        return zones

    current_type = pos_types[0]
    zone_start = 0

    for i in range(1, len(pos_types)):
        if pos_types[i] != current_type:
            # Zone boundary
            if current_type != "space" or (i - zone_start) <= 3:
                # Include small space gaps in adjacent zones
                if current_type != "space":
                    zones.append(FieldZone(
                        start=zone_start, end=i, width=i - zone_start,
                        field_type=current_type,
                    ))
            else:
                # Large space gap = padding/separator
                zones.append(FieldZone(
                    start=zone_start, end=i, width=i - zone_start,
                    field_type="padding",
                ))
            zone_start = i
            current_type = pos_types[i]

    # Final zone
    if zone_start < len(pos_types):
        zones.append(FieldZone(
            start=zone_start, end=len(pos_types), width=len(pos_types) - zone_start,
            field_type=current_type,
        ))

    # Merge adjacent zones of same type (after small-gap handling)
    merged = []
    for zone in zones:
        if zone.field_type == "padding" and zone.width <= 2:
            # Tiny padding — merge with previous zone
            if merged:
                merged[-1].end = zone.end
                merged[-1].width = merged[-1].end - merged[-1].start
            continue
        if merged and merged[-1].field_type == zone.field_type:
            merged[-1].end = zone.end
            merged[-1].width = merged[-1].end - merged[-1].start
        else:
            merged.append(zone)

    # Extract sample values for each non-padding zone
    for zone in merged:
        if zone.field_type == "padding":
            continue
        seen = set()
        for rec in sample[:20]:
            val = rec[zone.start:zone.end].strip() if zone.start < len(rec) else ""
            if val and val not in seen:
                zone.sample_values.append(val)
                seen.add(val)

    return merged


def _merge_date_zones(zones: list[FieldZone], records: list[str]) -> list[FieldZone]:
    """
    Detect date patterns that span multiple adjacent zones (e.g., 01/15/2024
    splits into digit, mixed, digit, mixed, digit) and merge them into a
    single date zone.
    """
    if len(zones) < 3 or not records:
        return zones

    merged = []
    i = 0
    while i < len(zones):
        # Look for pattern: digit(1-2) + mixed(1) + digit(1-2) + mixed(1) + digit(2-4)
        # which is the classic MM/DD/YYYY or similar date format
        if (i + 4 < len(zones) and
            zones[i].field_type == "digit" and zones[i].width <= 2 and
            zones[i+1].field_type == "mixed" and zones[i+1].width == 1 and
            zones[i+2].field_type == "digit" and zones[i+2].width <= 2 and
            zones[i+3].field_type == "mixed" and zones[i+3].width == 1 and
            zones[i+4].field_type == "digit" and zones[i+4].width <= 4):
            # Verify by sampling — extract the combined bytes and check if they're dates
            start = zones[i].start
            end = zones[i+4].end
            date_like = 0
            sample_vals = []
            for rec in records[:20]:
                val = rec[start:end].strip() if start < len(rec) else ""
                if val:
                    sample_vals.append(val)
                    if re.match(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", val):
                        date_like += 1
            if date_like >= len(sample_vals) * 0.5 and date_like > 0:
                # Merge into a single date zone
                merged_zone = FieldZone(
                    start=start, end=end, width=end - start,
                    field_type="date", sample_values=sample_vals[:5],
                )
                merged.append(merged_zone)
                i += 5
                continue

        merged.append(zones[i])
        i += 1

    return merged


def _classify_zones(zones: list[FieldZone]) -> list[FieldZone]:
    """
    Assign labels to field zones based on their content patterns.

    Uses content-aware heuristics to detect specific field types:
    - Date fields (DOB, service dates)
    - US state abbreviations
    - ZIP codes (5-digit or 5+4)
    - Phone numbers (10-digit, formatted)
    - Insurance/policy numbers
    - Last name / first name (consecutive alpha fields)
    - City names (alpha fields after name fields, before state)
    - Generic IDs (numeric fields)
    """
    id_count = 0
    name_count = 0
    date_count = 0
    text_count = 0

    # First pass: detect high-confidence content types (dates, states)
    for zone in zones:
        zone._detected = None  # Temporary attribute for classification

        if zone.field_type == "padding":
            zone.label = "padding"
            continue

        samples = zone.sample_values[:10]
        if not samples:
            continue

        # --- Date detection ---
        date_like = 0
        for val in samples:
            if _RE_DATE.match(val) or _RE_DATE_ISO.match(val):
                date_like += 1
            elif _RE_DATE_COMPACT.match(val) and len(val) == 8:
                date_like += 1
        if zone.field_type == "date" or (date_like >= len(samples) * 0.5 and date_like > 0):
            zone._detected = "date"
            continue

        # --- US state abbreviation (2-char alpha, matches state list) ---
        if zone.field_type == "alpha" and zone.width <= 3:
            state_match = sum(1 for v in samples if v.strip().upper() in US_STATES)
            if state_match >= len(samples) * 0.5 and state_match > 0:
                zone._detected = "state"
                continue

        # --- Phone number (10-digit, width 10-14) ---
        if zone.width >= 7 and zone.width <= 15:
            phone_match = sum(1 for v in samples if _RE_PHONE.match(v.strip()))
            if phone_match >= len(samples) * 0.4 and phone_match > 0:
                zone._detected = "phone"
                continue

        # --- Insurance / policy number (alphanumeric with letter prefix, 6-15 chars) ---
        if zone.field_type in ("mixed",) and 6 <= zone.width <= 20:
            ins_match = sum(1 for v in samples if _RE_INSURANCE.match(v.strip()))
            if ins_match >= len(samples) * 0.4 and ins_match > 0:
                zone._detected = "insurance"
                continue

    # Second pass: find state positions, then detect ZIP codes near them
    state_indices = [i for i, z in enumerate(zones) if z._detected == "state"]
    date_indices = [i for i, z in enumerate(zones) if z._detected == "date"]

    for i, zone in enumerate(zones):
        if zone._detected is not None or zone.field_type == "padding":
            continue
        samples = zone.sample_values[:10]
        if not samples:
            continue

        # ZIP code: 5-digit numeric field that is NEAR a state field (within 3 positions)
        if zone.field_type in ("digit", "mixed") and 4 <= zone.width <= 11:
            near_state = any(abs(i - si) <= 3 for si in state_indices)
            if near_state:
                zip_match = sum(1 for v in samples if _RE_ZIP.match(v.strip()))
                if zip_match >= len(samples) * 0.5 and zip_match > 0:
                    zone._detected = "zip"
                    continue

    # Third pass: detect name fields vs city fields using positional context
    # In medical billing, typical order is: IDs, last name, first name, DOB,
    # address (city, state, zip), phone, insurance
    first_date_idx = date_indices[0] if date_indices else None
    first_state_idx = state_indices[0] if state_indices else None
    zip_indices = [i for i, z in enumerate(zones) if z._detected == "zip"]
    first_zip_idx = zip_indices[0] if zip_indices else None

    alpha_name_candidates = []
    for i, zone in enumerate(zones):
        if zone._detected is None and zone.field_type == "alpha" and zone.width >= 5:
            alpha_name_candidates.append(i)

    # Classify alpha fields: ones before the first date/state/zip are likely names,
    # ones near state/zip are likely city
    for idx in alpha_name_candidates:
        zone = zones[idx]
        near_state_zip = False
        if first_state_idx is not None and abs(idx - first_state_idx) <= 2:
            near_state_zip = True
        if first_zip_idx is not None and abs(idx - first_zip_idx) <= 2:
            near_state_zip = True

        # If close to state/zip, it's a city
        if near_state_zip and zone.width >= 5:
            zone._detected = "city"
        elif first_date_idx is None or idx < first_date_idx:
            # Before any date field = likely a name
            zone._detected = "name"
        elif zone.width >= 10:
            # Large alpha field after date but not near state/zip
            zone._detected = "name"
        else:
            zone._detected = None  # Leave for generic classification

    # Third pass: assign labels
    phone_count = 0
    zip_count = 0
    state_count = 0
    city_count = 0
    insurance_count = 0

    for zone in zones:
        if zone.field_type == "padding":
            continue

        det = getattr(zone, "_detected", None)

        if det == "date":
            date_count += 1
            zone.label = f"date_{date_count}"
            zone.field_type = "date"
        elif det == "state":
            state_count += 1
            zone.label = f"state_{state_count}"
        elif det == "zip":
            zip_count += 1
            zone.label = f"zip_{zip_count}"
        elif det == "phone":
            phone_count += 1
            zone.label = f"phone_{phone_count}"
        elif det == "insurance":
            insurance_count += 1
            zone.label = f"insurance_{insurance_count}"
        elif det == "city":
            city_count += 1
            zone.label = f"city_{city_count}"
        elif det == "name":
            name_count += 1
            zone.label = f"name_{name_count}"
        elif zone.field_type == "digit":
            id_count += 1
            zone.label = f"id_{id_count}"
        elif zone.field_type == "alpha":
            if zone.width >= 10:
                name_count += 1
                zone.label = f"name_{name_count}"
            else:
                text_count += 1
                zone.label = f"text_{text_count}"
        else:
            text_count += 1
            zone.label = f"field_{text_count}"

        # Clean up temporary attribute
        if hasattr(zone, "_detected"):
            del zone._detected

    return zones


def _parse_date(val: str) -> str | None:
    """Try to parse a date string into ISO format."""
    val = val.strip()
    if not val:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y",
                "%Y%m%d", "%m%d%Y", "%d/%m/%Y"):
        try:
            d = datetime.strptime(val, fmt).date()
            if 2000 <= d.year <= 2030:
                return d.isoformat()
        except ValueError:
            continue
    return None


def parse_fixed_width_records(
    content: bytes | str,
    record_width: int | None = None,
) -> FixedWidthResult:
    """
    Parse a fixed-width record file.

    Args:
        content: Raw file content (bytes or string)
        record_width: Override record width (auto-detected if None)

    Returns:
        FixedWidthResult with records, detected fields, and metadata
    """
    result = FixedWidthResult()

    # Detect record width
    if record_width is None:
        record_width = detect_record_width(content)
    if record_width is None:
        result.warnings.append(
            "Could not detect fixed record width. File may not be fixed-width format."
        )
        return result

    result.record_width = record_width
    data_width = record_width - 2  # Subtract CRLF

    result.format_info = f"Fixed-width: {record_width} bytes/record ({data_width} data + 2 CRLF)"

    # Split into records
    records = _split_into_records(content, record_width)
    result.total_records = len(records)

    if not records:
        result.warnings.append("No records found")
        return result

    logger.info(f"Fixed-width parser: {len(records)} records, {record_width} bytes/record")

    # Analyze field zones
    zones = _analyze_field_zones(records, data_width)
    zones = _merge_date_zones(zones, records)
    zones = _classify_zones(zones)

    # Filter out pure padding zones for output
    data_zones = [z for z in zones if z.field_type != "padding"]

    result.field_zones = [
        {
            "label": z.label,
            "start": z.start,
            "end": z.end,
            "width": z.width,
            "type": z.field_type,
            "sample_values": z.sample_values[:5],
        }
        for z in data_zones
    ]

    # Identify field types
    result.id_fields = [z.label for z in data_zones if z.label.startswith("id_")]
    result.name_fields = [z.label for z in data_zones if z.label.startswith("name_")]
    result.date_fields = [z.label for z in data_zones if z.label.startswith("date_")]
    result.phone_fields = [z.label for z in data_zones if z.label.startswith("phone_")]
    result.zip_fields = [z.label for z in data_zones if z.label.startswith("zip_")]
    result.state_fields = [z.label for z in data_zones if z.label.startswith("state_")]
    result.city_fields = [z.label for z in data_zones if z.label.startswith("city_")]
    result.insurance_fields = [z.label for z in data_zones if z.label.startswith("insurance_")]

    # Extract records — line number (1-indexed) IS the Topaz patient ID
    # In .NET server exports, record position corresponds to the patient's
    # Topaz billing system ID. Record #9125 = Topaz patient 9125.
    for line_num, rec in enumerate(records, start=1):
        row = {"_line_num": line_num, "_topaz_id": str(line_num)}
        for zone in data_zones:
            val = rec[zone.start:zone.end].strip() if zone.start < len(rec) else ""
            if val:
                if zone.field_type == "date":
                    parsed = _parse_date(val)
                    row[zone.label] = parsed if parsed else val
                else:
                    row[zone.label] = val
        result.records.append(row)

    return result


def looks_like_fixed_width(content: bytes | str) -> bool:
    """
    Quick heuristic: does this content look like a fixed-width record file?

    Checks for consistent line lengths and lack of common delimiters.
    """
    if isinstance(content, str):
        raw = content.encode("utf-8", errors="replace")
    else:
        raw = content

    # Need reasonable file size
    if len(raw) < 500:
        return False

    # Check for CRLF-delimited lines with consistent length
    if b"\r\n" in raw[:1000]:
        lines = raw.split(b"\r\n")
        if lines and not lines[-1]:
            lines = lines[:-1]
        if len(lines) < 10:
            return False
        lengths = {}
        for line in lines[:200]:
            ll = len(line)
            if ll > 0:
                lengths[ll] = lengths.get(ll, 0) + 1
        if not lengths:
            return False
        most_common = max(lengths, key=lengths.get)
        count = lengths[most_common]
        total = sum(lengths.values())
        # 80%+ consistency + reasonable width
        if count / total >= 0.8 and 30 <= most_common <= 1000:
            # Make sure it's not a delimited format disguised as fixed-width
            sample_text = raw[:3000].decode("utf-8", errors="replace")
            pipe_count = sample_text.count("|")
            tab_count = sample_text.count("\t")
            lines_checked = min(len(lines), 20)
            # If avg delimiters per line > 2, it's probably delimited
            if pipe_count / lines_checked > 2 or tab_count / lines_checked > 2:
                return False
            return True

    # Check file size divisibility
    for width in CANDIDATE_WIDTHS:
        if len(raw) >= width * 100 and len(raw) % width == 0:
            return True

    return False
