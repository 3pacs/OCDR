"""Tests for ocdr.normalizers."""

import pytest
from datetime import date
from decimal import Decimal

from ocdr.normalizers import (
    normalize_patient_name, normalize_physician_name, normalize_payer_code,
    normalize_decimal, normalize_gado, normalize_modality, normalize_scan_type,
    excel_serial_to_date, date_to_excel_serial, parse_date_flexible,
    derive_month, derive_year,
    map_candelis_modality, detect_gado_from_desc, detect_psma,
    extract_scan_type,
)


# ── Name normalisation ───────────────────────────────────────────────────

class TestNormalizePatientName:
    def test_comma_separated(self):
        assert normalize_patient_name("TORRES, JULIA") == "TORRES, JULIA"

    def test_comma_separated_lowercase(self):
        assert normalize_patient_name("torres, julia") == "TORRES, JULIA"

    def test_caret_separated(self):
        assert normalize_patient_name("PATINO^MARGARET") == "PATINO, MARGARET"

    def test_caret_with_middle(self):
        assert normalize_patient_name("SMITH^JOHN^M") == "SMITH, JOHN"

    def test_research_numeric_id(self):
        """RESEARCH IDs like 548^23065^^^ should NOT use LAST, FIRST format."""
        result = normalize_patient_name("548^23065^^^")
        assert result == "548 23065"

    def test_research_name_caret(self):
        assert normalize_patient_name("BUEZO NUNEZ^JUAN") == "BUEZO NUNEZ, JUAN"

    def test_empty(self):
        assert normalize_patient_name("") == ""
        assert normalize_patient_name(None) == ""

    def test_whitespace(self):
        assert normalize_patient_name("  TORRES , JULIA  ") == "TORRES, JULIA"

    def test_single_name(self):
        assert normalize_patient_name("SMITH") == "SMITH"


# ── Date normalisation ───────────────────────────────────────────────────

class TestDateNormalisation:
    def test_excel_serial(self):
        # 45689 should be a valid date in 2025
        result = excel_serial_to_date(45689)
        assert result is not None
        assert isinstance(result, date)

    def test_excel_serial_zero(self):
        assert excel_serial_to_date(0) is None

    def test_excel_serial_none(self):
        assert excel_serial_to_date(None) is None

    def test_date_to_serial_roundtrip(self):
        d = date(2025, 1, 15)
        serial = date_to_excel_serial(d)
        result = excel_serial_to_date(serial)
        assert result == d

    def test_parse_date_mm_dd_yyyy(self):
        assert parse_date_flexible("02/16/1974") == date(1974, 2, 16)

    def test_parse_date_iso(self):
        assert parse_date_flexible("2025-01-15") == date(2025, 1, 15)

    def test_parse_date_none(self):
        assert parse_date_flexible(None) is None
        assert parse_date_flexible("") is None

    def test_parse_date_datetime(self):
        from datetime import datetime
        dt = datetime(2025, 3, 1, 10, 30)
        assert parse_date_flexible(dt) == date(2025, 3, 1)

    def test_parse_date_object(self):
        d = date(2025, 6, 15)
        assert parse_date_flexible(d) == d

    def test_derive_month(self):
        assert derive_month(date(2025, 1, 15)) == "Jan"
        assert derive_month(date(2025, 12, 1)) == "Dec"
        assert derive_month(None) == ""

    def test_derive_year(self):
        assert derive_year(date(2025, 1, 15)) == "2025"
        assert derive_year(None) == ""


# ── Payer normalisation ──────────────────────────────────────────────────

class TestNormalizePayer:
    def test_exact_match(self):
        assert normalize_payer_code("M/M") == "M/M"

    def test_alias(self):
        assert normalize_payer_code("SELFPAY") == "SELF PAY"
        assert normalize_payer_code("CASH") == "SELF PAY"
        assert normalize_payer_code("MEDICARE") == "M/M"

    def test_none(self):
        assert normalize_payer_code(None) == ""

    def test_unknown(self):
        assert normalize_payer_code("ACME INSURANCE") == "ACME INSURANCE"


# ── Monetary normalisation ───────────────────────────────────────────────

class TestNormalizeDecimal:
    def test_number_string(self):
        assert normalize_decimal("750.00") == Decimal("750.00")

    def test_dollar_sign(self):
        assert normalize_decimal("$1,250.50") == Decimal("1250.50")

    def test_none(self):
        assert normalize_decimal(None) == Decimal("0.00")

    def test_empty(self):
        assert normalize_decimal("") == Decimal("0.00")

    def test_decimal_passthrough(self):
        assert normalize_decimal(Decimal("123.456")) == Decimal("123.46")


# ── Boolean normalisation ────────────────────────────────────────────────

class TestNormalizeGado:
    def test_yes(self):
        assert normalize_gado("YES") is True
        assert normalize_gado("yes") is True

    def test_no(self):
        assert normalize_gado("NO") is False
        assert normalize_gado("") is False
        assert normalize_gado(None) is False


# ── Candelis modality mapping ────────────────────────────────────────────

class TestMapCandelisModality:
    def test_pet_ct_description(self):
        mod, conf = map_candelis_modality("CT/SR/PT/SC", "PET/CT")
        assert mod == "PET"
        assert conf == 1.0

    def test_mr_brain_gado(self):
        mod, conf = map_candelis_modality("MR", "BRAIN-GADO")
        assert mod == "HMRI"
        assert conf == 1.0

    def test_mr_lsp(self):
        mod, conf = map_candelis_modality("MR", "LSP")
        assert mod == "HMRI"
        assert conf == 1.0

    def test_sr_ct_cap(self):
        """SR/CT machine with C.A.P description → CT."""
        mod, conf = map_candelis_modality("SR/CT", "C.A.P")
        assert mod == "CT"
        assert conf == 1.0

    def test_dx_pa_views(self):
        mod, conf = map_candelis_modality("DX", "PA VIEWS OF RT KNEE")
        assert mod == "DX"
        assert conf == 1.0

    def test_bone_scan(self):
        mod, conf = map_candelis_modality("NM", "BONE SCAN")
        assert mod == "BONE"
        assert conf == 1.0

    def test_ambiguous_pt_no_desc(self):
        """PT in codes but description doesn't say PET → low confidence."""
        mod, conf = map_candelis_modality("CT/SR/PT/SC", "C.A.P")
        assert conf < 1.0

    def test_unknown_fallback(self):
        mod, conf = map_candelis_modality("", "")
        assert mod == ""
        assert conf == 0.0

    def test_mr_open_in_description(self):
        mod, conf = map_candelis_modality("MR", "OPEN MRI BRAIN")
        assert mod == "OPEN"
        assert conf == 1.0


class TestDetectGado:
    def test_gado_suffix(self):
        assert detect_gado_from_desc("BRAIN-GADO") is True

    def test_gado_word(self):
        assert detect_gado_from_desc("LSP GADO") is True

    def test_no_gado(self):
        assert detect_gado_from_desc("BRAIN") is False
        assert detect_gado_from_desc("") is False


class TestDetectPSMA:
    def test_psma(self):
        assert detect_psma("PSMA PET/CT") is True

    def test_ga68(self):
        assert detect_psma("GA-68 SCAN") is True

    def test_gallium(self):
        assert detect_psma("GALLIUM SCAN") is True

    def test_normal(self):
        assert detect_psma("BRAIN-GADO") is False


class TestExtractScanType:
    def test_cap(self):
        assert extract_scan_type("C.A.P") == "ABDOMEN"

    def test_brain(self):
        assert extract_scan_type("BRAIN-GADO") == "HEAD"

    def test_head(self):
        assert extract_scan_type("HEAD") == "HEAD"

    def test_chest(self):
        assert extract_scan_type("CHEST") == "CHEST"

    def test_chest_ld(self):
        assert extract_scan_type("CHEST L.D.") == "CHEST"

    def test_lsp(self):
        assert extract_scan_type("LSP") == "LUMBAR"

    def test_lsp_gado(self):
        assert extract_scan_type("LSP-GADO") == "LUMBAR"

    def test_csp(self):
        assert extract_scan_type("CSP") == "CERVICAL"

    def test_knee(self):
        assert extract_scan_type("RT KNEE") == "KNEE"
        assert extract_scan_type("LT KNEE") == "KNEE"

    def test_foot(self):
        assert extract_scan_type("RT FOOT") == "FOOT"

    def test_shoulder(self):
        assert extract_scan_type("RT SHLDR") == "SHOULDER"
        assert extract_scan_type("ARTH SHOULD RT") == "SHOULDER"

    def test_pelvis(self):
        assert extract_scan_type("PELVIS") == "PELVIS"

    def test_pet(self):
        assert extract_scan_type("PET/CT") == "WHOLE BODY"

    def test_bone_scan(self):
        assert extract_scan_type("BONE SCAN") == "WHOLE BODY"

    def test_empty(self):
        assert extract_scan_type("") == ""

    def test_stn_cap(self):
        """STN/C.A.P should map via C.A.P match."""
        result = extract_scan_type("STN/C.A.P")
        assert result in ("ABDOMEN", "SINUS")  # C.A.P or STN match
