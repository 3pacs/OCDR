"""Topaz Legacy Data Importer.

Imports data from the Topaz system (bespoke .NET application, originally DOS-era).
Topaz stores data as flat text files in X:\\tpzservr\\.

The file format is unknown and must be reverse-engineered from sample data.
Known characteristics:
  - Files have NO file extensions (just bare names, no .txt/.dat/.csv)
  - Encoding: likely CP437 or ASCII (DOS era)
  - Structure: likely fixed-width fields or custom delimiters
  - Dates: probably MM/DD/YY or MMDDYY (2-digit years)
  - No headers: raw data, positional fields

Known file naming patterns (from directory listing):
  - Monthly data: MON1YYYY / MON2YYYY (e.g. JAN12025, FEB22026)
    MON = 3-letter month, 1/2 = sequence or half-month, YYYY = year
  - Lookup tables: patnt, doclst, inslst, reflst, cptlst, dxtlst, poslst
  - Patient data: PtNote, PtNote2, PtEMG, PtHosp, PtPOS, PtRMK, PtSec, PtStmnt, PtTrack2
  - Schedule: schdlx2, SchdlDiv
  - Daily files: daily1, daily2, daily3
  - Requisitions: req1 through req34
  - System files: BASIC14.EXE, RUN14.EXE, T_REPAIR.EXE
  - Config: *.WN8, *.mcl, *.mcr

Workflow:
  1. classify_file()   — Categorize by naming convention
  2. analyze_file()    — Detect encoding, record length, field boundaries
  3. detect_fields()   — Map byte positions to semantic fields (name, DOB, etc.)
  4. extract_records() — Parse file into dicts using detected field map
  5. import_records()  — Insert into OCDR database tables
"""

import os
import re
from collections import Counter

from app.import_engine.validation import parse_date, normalize_modality


# ── File classification ─────────────────────────────────────────

# Month abbreviations for matching monthly data files
_MONTHS = {
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
}

# Known Topaz file categories and their patterns
TOPAZ_FILE_CATEGORIES = {
    "monthly_billing": {
        "description": "Monthly billing/transaction data",
        "importance": "high",
        "pattern": "MON[12]YYYY (e.g. JAN12025)",
    },
    "patient_master": {
        "description": "Patient demographics and master records",
        "importance": "high",
        "files": ["patnt"],
    },
    "doctor_list": {
        "description": "Physician/doctor reference list",
        "importance": "medium",
        "files": ["doclst"],
    },
    "insurance_list": {
        "description": "Insurance carrier reference list",
        "importance": "high",
        "files": ["inslst", "ins", "ins4"],
    },
    "referring_list": {
        "description": "Referring physician list",
        "importance": "medium",
        "files": ["reflst"],
    },
    "cpt_list": {
        "description": "CPT/procedure code list",
        "importance": "high",
        "files": ["cptlst"],
    },
    "diagnosis_list": {
        "description": "Diagnosis code list",
        "importance": "medium",
        "files": ["dxtlst"],
    },
    "pos_list": {
        "description": "Place of service list",
        "importance": "low",
        "files": ["poslst"],
    },
    "patient_notes": {
        "description": "Patient clinical/admin notes",
        "importance": "medium",
        "files": ["PtNote", "PtNote2", "PtEMG", "PtHosp", "PtPOS",
                  "PtRMK", "PtSec", "PtStmnt", "PtTrack2"],
    },
    "schedule": {
        "description": "Appointment schedule data",
        "importance": "medium",
        "files": ["schdlx2", "SchdlDiv"],
    },
    "daily": {
        "description": "Daily transaction/activity logs",
        "importance": "medium",
        "prefix": "daily",
    },
    "requisitions": {
        "description": "Requisition/order forms",
        "importance": "low",
        "prefix": "req",
    },
    "records": {
        "description": "General record files",
        "importance": "medium",
        "files": ["rec"],
    },
    "kin": {
        "description": "Next of kin / emergency contacts",
        "importance": "low",
        "files": ["KIN"],
    },
    "word_processing": {
        "description": "Word processing templates",
        "importance": "low",
        "prefix": "WP",
    },
    "display_config": {
        "description": "Display color/config files",
        "importance": "skip",
        "prefix": "clr",
    },
    "level_config": {
        "description": "Access level configuration",
        "importance": "low",
        "prefix": "Level_",
    },
    "system_executable": {
        "description": "System executable (skip)",
        "importance": "skip",
        "extensions": [".EXE", ".exe"],
    },
    "system_config": {
        "description": "System configuration (skip)",
        "importance": "skip",
        "extensions": [".WN8", ".mcl", ".mcr", ".wn8"],
    },
}


def classify_file(filename):
    """Classify a Topaz file by its naming convention.

    Returns dict with:
        category (str), description (str), importance (str),
        is_monthly (bool), month (str or None), year (int or None),
        sequence (int or None)
    """
    basename = os.path.basename(filename)
    name_upper = basename.upper()

    # Check for system files by extension
    _, ext = os.path.splitext(basename)
    if ext:
        for cat, info in TOPAZ_FILE_CATEGORIES.items():
            if "extensions" in info and ext in info["extensions"]:
                return {
                    "category": cat,
                    "description": info["description"],
                    "importance": info["importance"],
                    "is_monthly": False,
                    "month": None,
                    "year": None,
                    "sequence": None,
                }

    # Check monthly billing pattern: MON[12]YYYY
    m = re.match(r"^([A-Z]{3})([12])(\d{4})$", name_upper)
    if m and m.group(1) in _MONTHS:
        month_str, seq, year_str = m.group(1), int(m.group(2)), int(m.group(3))
        if 1980 <= year_str <= 2099:
            return {
                "category": "monthly_billing",
                "description": TOPAZ_FILE_CATEGORIES["monthly_billing"]["description"],
                "importance": "high",
                "is_monthly": True,
                "month": month_str,
                "year": year_str,
                "sequence": seq,
            }

    # Check exact filename matches (case-insensitive)
    for cat, info in TOPAZ_FILE_CATEGORIES.items():
        if "files" in info:
            for known in info["files"]:
                if basename == known or name_upper == known.upper():
                    return {
                        "category": cat,
                        "description": info["description"],
                        "importance": info["importance"],
                        "is_monthly": False,
                        "month": None,
                        "year": None,
                        "sequence": None,
                    }

    # Check prefix matches
    for cat, info in TOPAZ_FILE_CATEGORIES.items():
        if "prefix" in info:
            prefix = info["prefix"]
            if basename.startswith(prefix) or name_upper.startswith(prefix.upper()):
                return {
                    "category": cat,
                    "description": info["description"],
                    "importance": info["importance"],
                    "is_monthly": False,
                    "month": None,
                    "year": None,
                    "sequence": None,
                }

    # Skip hidden files
    if basename.startswith("."):
        return {
            "category": "hidden",
            "description": "Hidden file (skip)",
            "importance": "skip",
            "is_monthly": False,
            "month": None,
            "year": None,
            "sequence": None,
        }

    # Unknown
    return {
        "category": "unknown",
        "description": "Unrecognized file — needs manual review",
        "importance": "unknown",
        "is_monthly": False,
        "month": None,
        "year": None,
        "sequence": None,
    }


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

    Classifies files by naming convention and analyzes structure.
    Returns list of analysis dicts sorted by importance then file size.
    """
    results = []
    if not os.path.isdir(dir_path):
        return results

    importance_order = {"high": 0, "medium": 1, "low": 2, "unknown": 3, "skip": 4}

    for fname in os.listdir(dir_path):
        fpath = os.path.join(dir_path, fname)
        if not os.path.isfile(fpath):
            continue

        # Classify by name
        classification = classify_file(fname)

        # Skip system/config files for structural analysis
        if classification["importance"] == "skip":
            results.append({
                "filename": fname,
                "file_size": os.path.getsize(fpath),
                "classification": classification,
                "skipped": True,
            })
            continue

        try:
            info = analyze_file(fpath)
            info["filename"] = fname
            info["classification"] = classification
            results.append(info)
        except Exception as e:
            results.append({
                "filename": fname,
                "error": str(e),
                "file_size": os.path.getsize(fpath),
                "classification": classification,
            })

    results.sort(key=lambda x: (
        importance_order.get(x.get("classification", {}).get("importance", "unknown"), 3),
        -(x.get("file_size", 0)),
    ))
    return results


def get_topaz_summary(dir_path):
    """Get a high-level summary of Topaz files without full analysis.

    Returns category counts, monthly file date ranges, and import priority.
    """
    if not os.path.isdir(dir_path):
        return {"error": "Directory not found", "path": dir_path}

    categories = Counter()
    monthly_files = []
    total_size = 0
    file_count = 0

    for fname in os.listdir(dir_path):
        fpath = os.path.join(dir_path, fname)
        if not os.path.isfile(fpath):
            continue

        file_count += 1
        fsize = os.path.getsize(fpath)
        total_size += fsize

        classification = classify_file(fname)
        categories[classification["category"]] += 1

        if classification["is_monthly"]:
            monthly_files.append({
                "filename": fname,
                "month": classification["month"],
                "year": classification["year"],
                "sequence": classification["sequence"],
                "size": fsize,
            })

    # Sort monthly files chronologically
    monthly_files.sort(key=lambda x: (x["year"], _MONTHS_LIST.index(x["month"])
                                      if x["month"] in _MONTHS_LIST else 0,
                                      x["sequence"]))

    date_range = None
    if monthly_files:
        first = monthly_files[0]
        last = monthly_files[-1]
        date_range = {
            "earliest": f"{first['month']} {first['year']}",
            "latest": f"{last['month']} {last['year']}",
            "total_months": len(monthly_files),
        }

    return {
        "path": dir_path,
        "file_count": file_count,
        "total_size_bytes": total_size,
        "categories": dict(categories),
        "monthly_date_range": date_range,
        "monthly_files": monthly_files,
        "high_priority": [cat for cat, info in TOPAZ_FILE_CATEGORIES.items()
                         if info["importance"] == "high"],
    }


# Ordered month list for sorting
_MONTHS_LIST = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
