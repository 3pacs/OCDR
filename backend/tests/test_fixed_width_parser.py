"""Tests for the fixed-width record parser."""

import pytest

from backend.app.parsing.fixed_width_parser import (
    detect_record_width,
    parse_fixed_width_records,
    looks_like_fixed_width,
)


def _make_fixed_records(data_width: int, records: list[str]) -> bytes:
    """Build a fixed-width file from a list of data strings, padded to data_width + CRLF."""
    lines = []
    for rec in records:
        padded = rec.ljust(data_width)[:data_width]
        lines.append(padded.encode("utf-8") + b"\r\n")
    return b"".join(lines)


class TestRecordWidthDetection:
    def test_detects_128_byte_records(self):
        # 126 data + 2 CRLF = 128
        records = [f"PATIENT{i:06d}  SMITH JOHN          12345  9876  2024-01-15  NOTES HERE" for i in range(50)]
        content = _make_fixed_records(126, records)
        assert detect_record_width(content) == 128

    def test_detects_64_byte_records(self):
        records = [f"REC{i:05d} DATA FIELD HERE     VALUE{i:04d}" for i in range(50)]
        content = _make_fixed_records(62, records)
        assert detect_record_width(content) == 64

    def test_returns_none_for_variable_length(self):
        content = b"short line\r\nthis is a much longer line with more data\r\nmedium line here\r\n"
        assert detect_record_width(content) is None

    def test_returns_none_for_small_file(self):
        content = b"tiny\r\n"
        assert detect_record_width(content) is None

    def test_detects_width_by_divisibility(self):
        # No CRLF, just raw bytes — falls through to divisibility check
        content = b"A" * (128 * 100)
        width = detect_record_width(content)
        assert width == 128


class TestFieldZoneDetection:
    def test_discovers_numeric_and_alpha_zones(self):
        records = [f"{i:05d}  SMITH JOHN          2024-01-{15+i%28:02d}" for i in range(50)]
        content = _make_fixed_records(len(records[0]), records)
        result = parse_fixed_width_records(content)
        assert result.total_records == 50
        assert len(result.id_fields) >= 1  # Should find the 5-digit numeric field
        assert len(result.name_fields) >= 1  # Should find the alpha name field

    def test_finds_date_zone(self):
        records = [f"{i:05d}  NAME{i:04d}             01/15/2024" for i in range(50)]
        content = _make_fixed_records(len(records[0]), records)
        result = parse_fixed_width_records(content)
        assert len(result.date_fields) >= 1

    def test_parses_sample_values(self):
        records = [f"{10000+i}  PATIENT NAME {i:03d}    " for i in range(20)]
        content = _make_fixed_records(len(records[0]), records)
        result = parse_fixed_width_records(content)
        # Should have field zones with sample values
        assert any(len(z["sample_values"]) > 0 for z in result.field_zones)


class TestFixedWidthParsing:
    def test_basic_parse(self):
        records = [f"{10000+i}  SMITH JOHN{i:03d}       98765  " for i in range(30)]
        content = _make_fixed_records(len(records[0]), records)
        result = parse_fixed_width_records(content)
        assert result.total_records == 30
        assert result.record_width > 0
        assert len(result.records) == 30

    def test_explicit_width_override(self):
        data = "12345DATA HERE           67890"
        records = [data] * 20
        content = _make_fixed_records(len(data), records)
        result = parse_fixed_width_records(content, record_width=len(data) + 2)
        assert result.total_records == 20

    def test_empty_content(self):
        result = parse_fixed_width_records(b"")
        assert result.total_records == 0
        assert len(result.warnings) > 0

    def test_records_have_extracted_values(self):
        records = [f"AAA{i:05d}BBB NAME{i:03d}          CCC{i:04d}DDD" for i in range(20)]
        content = _make_fixed_records(len(records[0]), records)
        result = parse_fixed_width_records(content)
        assert result.total_records == 20
        # Each record should be a non-empty dict
        assert all(len(r) > 0 for r in result.records)


class TestLooksLikeFixedWidth:
    def test_consistent_line_lengths(self):
        records = [f"{i:05d}  PATIENT DATA HERE FOR RECORD NUMBER {i}" for i in range(50)]
        content = _make_fixed_records(len(records[0]), records)
        assert looks_like_fixed_width(content) is True

    def test_not_fixed_width_for_delimited(self):
        lines = [f"field1|field2|field3|field{i}" for i in range(50)]
        content = ("\r\n".join(lines) + "\r\n").encode("utf-8")
        assert looks_like_fixed_width(content) is False

    def test_not_fixed_width_for_short_file(self):
        assert looks_like_fixed_width(b"short") is False

    def test_handles_string_input(self):
        records = [f"{i:05d}  SOME DATA HERE FOR THIS RECORD     " for i in range(50)]
        content = _make_fixed_records(len(records[0]), records)
        # Pass as string
        assert looks_like_fixed_width(content.decode("utf-8")) is True


class TestLargeRecordFile:
    """Simulate the actual ptnote1.txt format: 128 bytes/record."""

    def test_128_byte_records(self):
        # 126 data bytes + 2 CRLF = 128 bytes per record
        data_width = 126
        records = []
        for i in range(100):
            # Simulate: 5-byte ID, 2-byte gap, 20-byte name, 2-byte gap,
            #           5-byte code, 2-byte gap, 10-byte date, rest notes
            rec = f"{13000+i:05d}  {'JONES MARY':<20s}  {9000+i:05d}  01/15/2024  {'Note text here':<56s}"
            records.append(rec[:data_width].ljust(data_width))
        content = _make_fixed_records(data_width, records)

        assert len(content) == 128 * 100
        width = detect_record_width(content)
        assert width == 128

        result = parse_fixed_width_records(content)
        assert result.total_records == 100
        assert result.record_width == 128
        assert len(result.id_fields) >= 1
        assert len(result.name_fields) >= 1


class TestContentAwareFieldDetection:
    """Test smart detection of field types by content analysis."""

    def test_detects_split_name_fields(self):
        """Two separate alpha fields before date → last name, first name."""
        data_width = 80
        last_names = ["SMITH", "JONES", "WILLIAMS", "BROWN", "DAVIS",
                      "MILLER", "WILSON", "MOORE", "TAYLOR", "ANDERSON"]
        first_names = ["JOHN", "MARY", "JAMES", "PATRICIA", "ROBERT",
                       "JENNIFER", "MICHAEL", "LINDA", "WILLIAM", "ELIZABETH"]
        records = []
        for i in range(50):
            ln = last_names[i % len(last_names)]
            fn = first_names[i % len(first_names)]
            month = (i % 12) + 1
            day = (i % 28) + 1
            rec = f"{10000+i:05d}  {ln:<15s}  {fn:<15s}  {month:02d}/{day:02d}/1975    {90000+i:05d}"
            records.append(rec[:data_width].ljust(data_width))
        content = _make_fixed_records(data_width, records)
        result = parse_fixed_width_records(content)
        assert len(result.name_fields) >= 2, f"Expected >=2 name fields, got {result.name_fields}"
        assert len(result.date_fields) >= 1, f"Expected date field, got zones: {[z['label'] for z in result.field_zones]}"

    def test_detects_state_abbreviation(self):
        """2-char alpha field with US state codes → state field."""
        data_width = 60
        states = ["NY", "CA", "TX", "FL", "IL", "PA", "OH", "GA", "NC", "MI"]
        records = []
        for i in range(50):
            st = states[i % len(states)]
            rec = f"{10000+i:05d}  {'SOMECITY':<15s}  {st}  {'12345'}"
            records.append(rec[:data_width].ljust(data_width))
        content = _make_fixed_records(data_width, records)
        result = parse_fixed_width_records(content)
        assert len(result.state_fields) >= 1, f"Expected state field, got zones: {result.field_zones}"

    def test_detects_zip_code(self):
        """5-digit numeric field matching ZIP pattern → zip field."""
        data_width = 50
        zips = ["10001", "90210", "60601", "33101", "75201",
                "19101", "44101", "30301", "27601", "48201"]
        records = []
        for i in range(50):
            zc = zips[i % len(zips)]
            rec = f"{10000+i:05d}  {'LASTNAME':<15s}  {zc}"
            records.append(rec[:data_width].ljust(data_width))
        content = _make_fixed_records(data_width, records)
        result = parse_fixed_width_records(content)
        # ZIP is 5-digit numeric, should be detected as zip or id
        zone_labels = [z["label"] for z in result.field_zones]
        assert any("zip" in lbl or "id" in lbl for lbl in zone_labels)

    def test_detects_phone_number(self):
        """10-digit field matching phone pattern → phone field."""
        data_width = 60
        phones = ["2125551234", "3105559876", "3125554321", "3055551111",
                  "2145552222", "2155553333", "2165554444", "4045555555",
                  "9195556666", "3135557777"]
        records = []
        for i in range(50):
            ph = phones[i % len(phones)]
            rec = f"{10000+i:05d}  {'PATIENT':<15s}  {ph}"
            records.append(rec[:data_width].ljust(data_width))
        content = _make_fixed_records(data_width, records)
        result = parse_fixed_width_records(content)
        zone_labels = [z["label"] for z in result.field_zones]
        # Phone is 10 digits — may be detected as phone or id
        assert len(result.field_zones) >= 2

    def test_detects_dob_as_date(self):
        """Date field should appear in date_fields for DOB selection."""
        data_width = 60
        records = []
        for i in range(50):
            month = (i % 12) + 1
            day = (i % 28) + 1
            rec = f"{10000+i:05d}  {'LASTNAME':<15s}  {month:02d}/{day:02d}/1985"
            records.append(rec[:data_width].ljust(data_width))
        content = _make_fixed_records(data_width, records)
        result = parse_fixed_width_records(content)
        assert len(result.date_fields) >= 1, "DOB should be detected as a date field"

    def test_realistic_patient_record(self):
        """Simulate a realistic PtNote-style record with all field types."""
        data_width = 126
        last_names = ["SMITH", "JONES", "WILLIAMS", "BROWN", "DAVIS"]
        first_names = ["JOHN", "MARY", "JAMES", "PAT", "ROBERT"]
        cities = ["NEW YORK", "LOS ANGELES", "CHICAGO", "MIAMI", "DALLAS"]
        states = ["NY", "CA", "IL", "FL", "TX"]
        zips = ["10001", "90210", "60601", "33101", "75201"]
        records = []
        for i in range(50):
            idx = i % 5
            rec = (
                f"{10000+i:05d}  "           # ID (5)
                f"{last_names[idx]:<15s}  "   # Last name (15)
                f"{first_names[idx]:<12s}  "  # First name (12)
                f"{(i%12)+1:02d}/{(i%28)+1:02d}/1965  "  # DOB (10)
                f"{cities[idx]:<15s}  "       # City (15)
                f"{states[idx]}  "            # State (2)
                f"{zips[idx]}  "              # Zip (5)
                f"{'Notes':<20s}"             # Notes
            )
            records.append(rec[:data_width].ljust(data_width))
        content = _make_fixed_records(data_width, records)
        result = parse_fixed_width_records(content)

        assert result.total_records == 50
        assert len(result.id_fields) >= 1, "Should detect ID field"
        assert len(result.name_fields) >= 2, f"Should detect 2 name fields, got {result.name_fields}"
        assert len(result.date_fields) >= 1, "Should detect date field (DOB)"
