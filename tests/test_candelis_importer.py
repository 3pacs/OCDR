"""Tests for ocdr.candelis_importer."""

import pytest
from datetime import date
from decimal import Decimal

from ocdr.candelis_importer import parse_candelis_paste


# Sample Candelis paste data (tab-separated)
SAMPLE_PASTE = (
    "Pending\t48436\t02/16/1974\tTORRES, JULIA\t02/02/2026\tMR\tBRAIN-GADO\t9\t1339\tAE_MRI\tO\n"
    "Pending\t\t\t\t02/02/2026\tMR\tLSP\t5\t600\tAE_MRI\tO\n"
    "Pending\t47890\t05/10/1960\tPATINO^MARGARET\t02/02/2026\tCT/SR/PT/SC\tPET/CT\t12\t2500\tAE_MRI\tO\n"
    "Pending\t50100\t03/22/1985\tSMITH, JOHN\t02/02/2026\tSR/CT\tC.A.P\t8\t1200\tAE_MRI\tO\n"
    "Pending\t99001\t01/01/1990\t548^23065^^^\t02/02/2026\tMR\tBRAIN\t6\t800\tRESEARCH\tO\n"
    "Pending\t44321\t07/15/1978\tGARCIA, MARIA\t02/02/2026\tDX\tPA VIEWS OF RT KNEE\t2\t100\tAE_MRI\tO\n"
)


class TestParseCandelisPaste:
    def test_basic_parse(self):
        records = parse_candelis_paste(SAMPLE_PASTE)
        assert len(records) > 0

    def test_name_normalisation(self):
        records = parse_candelis_paste(SAMPLE_PASTE)
        names = [r["patient_name"] for r in records]
        assert "TORRES, JULIA" in names
        assert "PATINO, MARGARET" in names

    def test_continuation_row(self):
        """Row 2 has no patient — should copy from row 1 (TORRES, JULIA)."""
        records = parse_candelis_paste(SAMPLE_PASTE)
        # Find the LSP record (continuation of TORRES, JULIA)
        lsp_records = [r for r in records if r.get("description") == "LSP"]
        assert len(lsp_records) == 1
        assert lsp_records[0]["patient_name"] == "TORRES, JULIA"

    def test_pet_ct_modality(self):
        records = parse_candelis_paste(SAMPLE_PASTE)
        pet_records = [r for r in records if "PET" in r.get("description", "")]
        assert len(pet_records) >= 1
        assert pet_records[0]["suggested_modality"] == "PET"
        assert pet_records[0]["modality_confidence"] == 1.0

    def test_brain_gado_modality(self):
        records = parse_candelis_paste(SAMPLE_PASTE)
        brain_records = [r for r in records if "BRAIN-GADO" in r.get("description", "")]
        assert len(brain_records) >= 1
        assert brain_records[0]["suggested_modality"] == "HMRI"
        assert brain_records[0]["gado_used"] is True

    def test_dx_modality(self):
        records = parse_candelis_paste(SAMPLE_PASTE)
        dx_records = [r for r in records if "PA VIEWS" in r.get("description", "")]
        assert len(dx_records) == 1
        assert dx_records[0]["suggested_modality"] == "DX"

    def test_research_kept(self):
        """RESEARCH entries should be kept, not filtered."""
        records = parse_candelis_paste(SAMPLE_PASTE)
        research = [r for r in records if r.get("is_research")]
        assert len(research) >= 1
        # Verify name was normalized (^ stripped)
        assert research[0]["patient_name"] == "548 23065"

    def test_research_name_normalisation(self):
        """Research numeric ID should be formatted without carets."""
        records = parse_candelis_paste(SAMPLE_PASTE)
        research = [r for r in records if r.get("is_research")]
        for r in research:
            assert "^" not in r["patient_name"]

    def test_cap_expansion(self):
        """C.A.P records should be expanded into 2 line items (non-research)."""
        records = parse_candelis_paste(SAMPLE_PASTE)
        cap_records = [r for r in records if r.get("cap_expansion")]
        assert len(cap_records) == 2  # Standard = CHEST + A/P
        scan_types = {r["scan_type"] for r in cap_records}
        assert "CHEST" in scan_types
        assert "A/P" in scan_types

    def test_service_dates_parsed(self):
        records = parse_candelis_paste(SAMPLE_PASTE)
        for r in records:
            assert r.get("service_date") is not None
            assert isinstance(r["service_date"], date)

    def test_source_field(self):
        records = parse_candelis_paste(SAMPLE_PASTE)
        for r in records:
            assert r["source"] == "CANDELIS"

    def test_review_flags_on_low_confidence(self):
        records = parse_candelis_paste(SAMPLE_PASTE)
        for r in records:
            if r.get("modality_confidence", 1.0) < 1.0:
                assert len(r.get("review_flags", [])) > 0

    def test_empty_input(self):
        records = parse_candelis_paste("")
        assert records == []

    def test_too_few_columns(self):
        bad_paste = "Pending\t48436\n"
        records = parse_candelis_paste(bad_paste)
        assert records == []


class TestContinuationRows:
    def test_multiple_continuations(self):
        """Multiple continuation rows for the same patient."""
        paste = (
            "Pending\t48436\t02/16/1974\tTORRES, JULIA\t02/02/2026\tMR\tBRAIN-GADO\t9\t1339\tAE_MRI\tO\n"
            "Pending\t\t\t\t02/02/2026\tMR\tLSP\t5\t600\tAE_MRI\tO\n"
            "Pending\t\t\t\t02/02/2026\tMR\tCSP\t4\t500\tAE_MRI\tO\n"
        )
        records = parse_candelis_paste(paste)
        # All 3 should have TORRES, JULIA as patient
        for r in records:
            assert r["patient_name"] == "TORRES, JULIA"
        assert len(records) == 3

    def test_continuation_no_previous(self):
        """Continuation row as first row — should be skipped."""
        paste = "Pending\t\t\t\t02/02/2026\tMR\tBRAIN\t5\t600\tAE_MRI\tO\n"
        records = parse_candelis_paste(paste)
        assert len(records) == 0
