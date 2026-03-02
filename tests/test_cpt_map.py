"""Tests for ocdr.cpt_map — CPT lookup and body-part synonyms."""

import pytest

from ocdr.cpt_map import (
    CPT_MAP, BODY_PART_SYNONYMS,
    normalize_body_part, are_body_parts_equivalent,
    lookup_cpt, enrich_claim_from_cpt,
)


# ── CPT Lookup ──────────────────────────────────────────────────────────

class TestCPTLookup:
    def test_known_cpt(self):
        result = lookup_cpt("70553")
        assert result == {"modality": "HMRI", "body_part": "HEAD"}

    def test_ct_abdomen(self):
        result = lookup_cpt("74178")
        assert result == {"modality": "CT", "body_part": "ABDOMEN"}

    def test_pet_whole_body(self):
        result = lookup_cpt("78816")
        assert result == {"modality": "PET", "body_part": "WHOLE BODY"}

    def test_unknown_cpt_returns_none(self):
        assert lookup_cpt("99999") is None

    def test_bone_scan(self):
        result = lookup_cpt("78306")
        assert result["modality"] == "BONE"
        assert result["body_part"] == "WHOLE BODY"

    def test_dx_chest(self):
        result = lookup_cpt("71046")
        assert result["modality"] == "DX"
        assert result["body_part"] == "CHEST"


# ── Body-Part Synonyms ─────────────────────────────────────────────────

class TestBodyPartSynonyms:
    def test_head_brain(self):
        assert are_body_parts_equivalent("HEAD", "BRAIN")

    def test_abdomen_ap(self):
        assert are_body_parts_equivalent("ABDOMEN", "A/P")

    def test_lumbar_lsp(self):
        assert are_body_parts_equivalent("LUMBAR", "LSP")

    def test_cervical_csp(self):
        assert are_body_parts_equivalent("CERVICAL", "CSP")

    def test_thoracic_tsp(self):
        assert are_body_parts_equivalent("THORACIC", "TSP")

    def test_whole_body_wb(self):
        assert are_body_parts_equivalent("WHOLE BODY", "WB")

    def test_case_insensitive(self):
        assert are_body_parts_equivalent("head", "BRAIN")

    def test_not_equivalent(self):
        assert not are_body_parts_equivalent("HEAD", "CHEST")

    def test_normalize_unknown(self):
        # Unknown terms should return as-is (uppercased)
        assert normalize_body_part("ELBOW") == "ELBOW"

    def test_abdomen_pelvis_synonym(self):
        assert are_body_parts_equivalent("ABDOMEN", "ABDOMEN/PELVIS")

    def test_spine_variants(self):
        assert are_body_parts_equivalent("LUMBAR", "L-SPINE")
        assert are_body_parts_equivalent("LUMBAR", "LSPINE")
        assert are_body_parts_equivalent("CERVICAL", "C-SPINE")
        assert are_body_parts_equivalent("THORACIC", "T-SPINE")


# ── Claim Enrichment ────────────────────────────────────────────────────

class TestEnrichClaim:
    def test_enriches_from_cpt_codes(self):
        claim = {"cpt_codes": ["70553"]}
        result = enrich_claim_from_cpt(claim)
        assert result["modality"] == "HMRI"
        assert result["scan_type"] == "HEAD"
        assert result["cpt_modality"] == "HMRI"
        assert result["cpt_body_part"] == "HEAD"

    def test_enriches_from_service_lines(self):
        claim = {"service_lines": [{"cpt_code": "74178"}]}
        result = enrich_claim_from_cpt(claim)
        assert result["modality"] == "CT"
        assert result["scan_type"] == "ABDOMEN"

    def test_does_not_overwrite_existing_modality(self):
        claim = {"cpt_codes": ["70553"], "modality": "CT"}
        result = enrich_claim_from_cpt(claim)
        assert result["modality"] == "CT"  # Not overwritten
        assert result["cpt_modality"] == "HMRI"  # CPT info still stored

    def test_unknown_cpt_no_enrichment(self):
        claim = {"cpt_codes": ["99999"]}
        result = enrich_claim_from_cpt(claim)
        assert "modality" not in result
        assert "scan_type" not in result

    def test_empty_cpt_codes(self):
        claim = {"cpt_codes": []}
        result = enrich_claim_from_cpt(claim)
        assert "modality" not in result

    def test_first_recognized_cpt_used(self):
        claim = {"cpt_codes": ["99999", "70553"]}
        result = enrich_claim_from_cpt(claim)
        assert result["modality"] == "HMRI"
