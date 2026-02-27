"""Topaz Legacy Data Importer.

Imports data from the Topaz system (bespoke 1980s DOS software).
Topaz stores data as flat text files in X:\\tpzservr\\.

The file format is unknown and must be reverse-engineered from sample data.
Expected characteristics (1980s DOS era):
  - Encoding: CP437 or ASCII
  - Structure: likely fixed-width fields or custom delimiters
  - Dates: probably MM/DD/YY or MMDDYY (2-digit years)
  - No headers: raw data, positional fields

Workflow:
  1. analyze_file()    — Detect encoding, record length, field boundaries
  2. detect_fields()   — Map byte positions to semantic fields (name, DOB, etc.)
  3. extract_records() — Parse file into dicts using detected field map
  4. import_records()  — Insert into OCDR database tables
"""

import os
import re
from collections import Counter

from app.import_engine.validation import parse_date, normalize_modality


# ── Encoding detection ───────────────────────────────────────────

# DOS-era files often use CP437. Try these in order.
ENCODINGS_TO_TRY = ["ascii", "cp437", "latin-1", "utf-8"]


def detect_encoding(file_path, sample_size=8192):
    """Read the first N bytes and determine the most likely encoding."""
    with open(file_path, "rb") as f:
        raw = f.read(sample_size)

    for enc in ENCODINGS_TO_TRY:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"  # fallback — decodes anything


# ── File analysis ────────────────────────────────────────────────

def analyze_file(file_path):
    """Analyze a Topaz text file and return structural metadata.

    Returns dict with:
        encoding, file_size, line_count, line_lengths (Counter),
        sample_lines (first 20), likely_fixed_width (bool),
        likely_delimiter (str or None), record_length (int or None)
    """
    encoding = detect_encoding(file_path)
    file_size = os.path.getsize(file_path)

    line_lengths = Counter()
    sample_lines = []
    line_count = 0

    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        for i, line in enumerate(f):
            stripped = line.rstrip("\n\r")
            line_lengths[len(stripped)] += 1
            line_count += 1
            if i < 20:
                sample_lines.append(stripped)

    # Detect if fixed-width: if >80% of lines share the same length
    likely_fixed_width = False
    record_length = None
    if line_lengths:
        most_common_len, most_common_count = line_lengths.most_common(1)[0]
        if most_common_count / max(line_count, 1) > 0.80:
            likely_fixed_width = True
            record_length = most_common_len

    # Detect delimiter: check for consistent pipe, tab, or other separator
    likely_delimiter = _detect_delimiter(sample_lines)

    return {
        "file_path": file_path,
        "encoding": encoding,
        "file_size": file_size,
        "line_count": line_count,
        "line_lengths": dict(line_lengths.most_common(10)),
        "sample_lines": sample_lines,
        "likely_fixed_width": likely_fixed_width,
        "likely_delimiter": likely_delimiter,
        "record_length": record_length,
    }


def _detect_delimiter(lines, candidates="|~^,\t;"):
    """Check if sample lines consistently use a single delimiter."""
    if not lines:
        return None

    for delim in candidates:
        counts = [line.count(delim) for line in lines if line.strip()]
        if not counts:
            continue
        # If every non-empty line has the same number of this char, and it's > 0
        if min(counts) > 0 and len(set(counts)) == 1:
            return delim

    return None


# ── Fixed-width field detection ──────────────────────────────────

def detect_field_boundaries(lines, record_length=None):
    """Detect likely field boundaries in fixed-width data.

    Looks for columns where spaces/transitions consistently occur.
    Returns list of (start, end) tuples representing field positions.
    """
    if not lines:
        return []

    max_len = record_length or max(len(l) for l in lines)

    # Count space frequency at each position across all lines
    space_freq = [0] * max_len
    for line in lines:
        padded = line.ljust(max_len)
        for i, ch in enumerate(padded):
            if ch == " ":
                space_freq[i] += 1

    # Field boundaries are positions where space frequency is high
    # (indicating padding between fields)
    threshold = len(lines) * 0.7
    in_gap = False
    boundaries = []
    field_start = 0

    for i in range(max_len):
        if space_freq[i] >= threshold:
            if not in_gap and i > field_start:
                boundaries.append((field_start, i))
            in_gap = True
        else:
            if in_gap:
                field_start = i
            in_gap = False

    # Capture last field
    if not in_gap and field_start < max_len:
        boundaries.append((field_start, max_len))

    return boundaries


# ── Record extraction ────────────────────────────────────────────

def extract_records_fixed_width(file_path, field_map, encoding="ascii"):
    """Extract records from a fixed-width file using a field map.

    field_map: dict of {field_name: (start, end)} positions
    Example: {"patient_name": (0, 30), "dob": (30, 38), "phone": (38, 48)}

    Yields dicts with field_name: value (stripped).
    """
    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        for line in f:
            stripped = line.rstrip("\n\r")
            if not stripped.strip():
                continue
            record = {}
            for field_name, (start, end) in field_map.items():
                if start < len(stripped):
                    val = stripped[start:min(end, len(stripped))].strip()
                    record[field_name] = val if val else None
                else:
                    record[field_name] = None
            yield record


def extract_records_delimited(file_path, field_names, delimiter="|",
                              encoding="ascii"):
    """Extract records from a delimited file.

    field_names: list of field names in column order.
    Yields dicts with field_name: value.
    """
    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        for line in f:
            stripped = line.rstrip("\n\r")
            if not stripped.strip():
                continue
            parts = stripped.split(delimiter)
            record = {}
            for i, name in enumerate(field_names):
                if name and i < len(parts):
                    record[name] = parts[i].strip() or None
                elif name:
                    record[name] = None
            yield record


# ── Date handling for 1980s formats ──────────────────────────────

def parse_topaz_date(val):
    """Parse dates in Topaz format (likely 2-digit year, various layouts).

    Tries: MMDDYY, MM/DD/YY, MM-DD-YY, YYMMDD, YYYY-MM-DD
    Uses parse_date() from validation.py as final fallback.
    """
    if not val or not val.strip():
        return None

    val = val.strip()

    # Try 6-digit packed: MMDDYY
    if re.match(r"^\d{6}$", val):
        mm, dd, yy = val[:2], val[2:4], val[4:6]
        year = _expand_2digit_year(int(yy))
        try:
            from datetime import date
            return date(year, int(mm), int(dd))
        except ValueError:
            pass

    # Try 8-digit: MMDDYYYY or YYYYMMDD
    if re.match(r"^\d{8}$", val):
        # Try MMDDYYYY first
        try:
            from datetime import date
            return date(int(val[4:8]), int(val[0:2]), int(val[2:4]))
        except ValueError:
            pass
        # Try YYYYMMDD
        try:
            from datetime import date
            return date(int(val[0:4]), int(val[4:6]), int(val[6:8]))
        except ValueError:
            pass

    # Try with separators: MM/DD/YY or MM-DD-YY
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", val)
    if m:
        mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        year = _expand_2digit_year(yy) if yy < 100 else yy
        try:
            from datetime import date
            return date(year, mm, dd)
        except ValueError:
            pass

    # Fallback to standard parser
    return parse_date(val)


def _expand_2digit_year(yy):
    """Expand 2-digit year: 00-49 → 2000s, 50-99 → 1900s."""
    if yy < 50:
        return 2000 + yy
    return 1900 + yy


# ── Hex dump utility for unknown formats ─────────────────────────

def hex_dump(file_path, num_bytes=512):
    """Return hex + ASCII dump of first N bytes for format analysis."""
    with open(file_path, "rb") as f:
        raw = f.read(num_bytes)

    lines = []
    for offset in range(0, len(raw), 16):
        chunk = raw[offset:offset + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08x}  {hex_part:<48}  {ascii_part}")

    return "\n".join(lines)


# ── High-level import orchestrator ───────────────────────────────

def analyze_topaz_directory(dir_path):
    """Scan a directory of Topaz files and return analysis of each.

    Returns list of analysis dicts sorted by file size (largest first).
    """
    results = []
    if not os.path.isdir(dir_path):
        return results

    for fname in os.listdir(dir_path):
        fpath = os.path.join(dir_path, fname)
        if os.path.isfile(fpath):
            try:
                info = analyze_file(fpath)
                info["filename"] = fname
                results.append(info)
            except Exception as e:
                results.append({
                    "filename": fname,
                    "error": str(e),
                    "file_size": os.path.getsize(fpath),
                })

    results.sort(key=lambda x: x.get("file_size", 0), reverse=True)
    return results
