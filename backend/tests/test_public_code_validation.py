"""Tests for public code table validation (CARC, CPT, claim status, etc.)."""

from datetime import date

from backend.app.analytics.public_code_tables import (
    CARC_CODES,
    VALID_CARC_CODES,
    CLAIM_STATUS_CODES,
    VALID_CLAIM_STATUS_CODES,
    PAYMENT_METHOD_CODES,
    VALID_PAYMENT_METHODS,
    RADIOLOGY_CPT_CODES,
    VALID_RADIOLOGY_CPT_CODES,
    CPT_TO_MODALITY_EXTENDED,
    CAS_GROUP_CODE_DESCRIPTIONS,
    VALID_CAS_GROUP_CODES,
    COMMON_RARC_CODES,
    DTM_QUALIFIER_CODES,
    lookup_carc,
    lookup_claim_status,
    lookup_cpt,
    cpt_to_modality,
    is_valid_cpt_format,
    is_radiology_cpt_range,
)
from backend.app.analytics.data_validation import (
    validate_era_claim_line,
    validate_era_payment,
    validate_billing_record,
    validate_era_batch,
    enrich_carc_description,
    enrich_claim_status_description,
    enrich_cpt_description,
    VALID_CLAIM_STATUSES,
    CLAIM_STATUS_LABELS,
    CAS_GROUP_CODES,
    COMMON_CAS_REASON_CODES,
    PAYMENT_METHODS,
    CPT_TO_MODALITY,
)


# ============================================================
# PUBLIC CODE TABLE INTEGRITY TESTS
# ============================================================

class TestCARCCodes:
    def test_carc_has_expected_count(self):
        """CARC table should have 200+ codes from the public standard."""
        assert len(CARC_CODES) >= 200

    def test_common_denial_codes_present(self):
        """Key denial reason codes should be in the table."""
        must_have = ["1", "2", "3", "4", "5", "16", "18", "29", "45", "50", "96", "97"]
        for code in must_have:
            assert code in VALID_CARC_CODES, f"CARC code {code} missing"

    def test_carc_descriptions_nonempty(self):
        """Every CARC code should have a non-empty description."""
        for code, desc in CARC_CODES.items():
            assert desc and len(desc) > 5, f"CARC {code} has empty/short description"

    def test_lookup_carc_known(self):
        assert lookup_carc("1") == "Deductible amount"
        assert lookup_carc("45") == "Charge exceeds fee schedule/maximum allowable or contracted/legislated fee arrangement"

    def test_lookup_carc_unknown(self):
        assert lookup_carc("9999") is None
        assert lookup_carc("") is None

    def test_carc_codes_are_numeric_strings(self):
        """All CARC codes should be numeric strings."""
        for code in VALID_CARC_CODES:
            assert code.isdigit(), f"CARC code '{code}' is not numeric"


class TestClaimStatusCodes:
    def test_has_standard_codes(self):
        """Must include the primary X12 835 claim status codes."""
        for code in ("1", "2", "4", "22", "23"):
            assert code in VALID_CLAIM_STATUS_CODES

    def test_expanded_codes_present(self):
        """New codes from full standard should be present."""
        for code in ("3", "5", "10", "13", "19", "20", "21", "25"):
            assert code in VALID_CLAIM_STATUS_CODES

    def test_lookup_claim_status(self):
        assert lookup_claim_status("1") == "Processed as Primary"
        assert lookup_claim_status("4") == "Denied"
        assert lookup_claim_status("22") == "Reversal of Previous Payment"

    def test_labels_match_codes(self):
        """CLAIM_STATUS_LABELS in data_validation should cover all standard codes."""
        for code in VALID_CLAIM_STATUS_CODES:
            assert code in CLAIM_STATUS_LABELS, f"Claim status {code} missing from CLAIM_STATUS_LABELS"


class TestPaymentMethods:
    def test_standard_methods(self):
        for method in ("CHK", "ACH", "NON", "FWT", "BOP"):
            assert method in VALID_PAYMENT_METHODS

    def test_single_char_codes(self):
        """X12 BPR01 also uses single-char codes."""
        for code in ("C", "D", "H", "I", "P", "U", "X"):
            assert code in VALID_PAYMENT_METHODS

    def test_descriptions(self):
        assert PAYMENT_METHOD_CODES["CHK"] == "Check"
        assert PAYMENT_METHOD_CODES["ACH"] == "Automated Clearing House"


class TestCASGroupCodes:
    def test_all_five_present(self):
        assert VALID_CAS_GROUP_CODES == frozenset({"CO", "CR", "OA", "PI", "PR"})

    def test_descriptions(self):
        assert "Contractual" in CAS_GROUP_CODE_DESCRIPTIONS["CO"]
        assert "Patient" in CAS_GROUP_CODE_DESCRIPTIONS["PR"]


class TestRadiologyCPTCodes:
    def test_has_substantial_count(self):
        """Should have 150+ radiology CPT codes."""
        assert len(RADIOLOGY_CPT_CODES) >= 150

    def test_key_ct_codes(self):
        for code in ("74177", "74178", "71260", "71250", "70450"):
            assert code in VALID_RADIOLOGY_CPT_CODES, f"CT code {code} missing"

    def test_key_mri_codes(self):
        for code in ("70551", "70553", "72141", "72148", "73721"):
            assert code in VALID_RADIOLOGY_CPT_CODES, f"MRI code {code} missing"

    def test_key_pet_codes(self):
        for code in ("78816", "78815", "78814", "78811"):
            assert code in VALID_RADIOLOGY_CPT_CODES, f"PET code {code} missing"

    def test_key_bone_codes(self):
        for code in ("78300", "78305", "78306"):
            assert code in VALID_RADIOLOGY_CPT_CODES, f"Bone code {code} missing"

    def test_key_xray_codes(self):
        for code in ("71045", "71046", "73030"):
            assert code in VALID_RADIOLOGY_CPT_CODES, f"X-ray code {code} missing"

    def test_descriptions_nonempty(self):
        for code, desc in RADIOLOGY_CPT_CODES.items():
            assert desc and len(desc) > 5, f"CPT {code} has empty description"

    def test_lookup_cpt(self):
        assert "chest" in lookup_cpt("71250").lower()
        assert lookup_cpt("99999") is None


class TestCPTToModality:
    def test_crosswalk_coverage(self):
        """All CPT codes should map to a known modality."""
        from backend.app.analytics.data_validation import VALID_MODALITIES
        for code, modality in CPT_TO_MODALITY_EXTENDED.items():
            assert modality in VALID_MODALITIES, f"CPT {code} maps to unknown modality {modality}"

    def test_ct_crosswalk(self):
        assert cpt_to_modality("74177") == "CT"
        assert cpt_to_modality("71250") == "CT"

    def test_mri_crosswalk(self):
        assert cpt_to_modality("70553") == "HMRI"
        assert cpt_to_modality("72148") == "HMRI"

    def test_pet_crosswalk(self):
        assert cpt_to_modality("78816") == "PET"

    def test_unknown_code(self):
        assert cpt_to_modality("00000") is None


class TestCPTFormat:
    def test_valid_5_digit(self):
        assert is_valid_cpt_format("74177") is True
        assert is_valid_cpt_format("78816") is True

    def test_valid_hcpcs_level_ii(self):
        """HCPCS Level II: letter + 4 digits."""
        assert is_valid_cpt_format("A0428") is True
        assert is_valid_cpt_format("J1234") is True

    def test_invalid_formats(self):
        assert is_valid_cpt_format("1234") is False
        assert is_valid_cpt_format("123456") is False
        assert is_valid_cpt_format("ABCDE") is False
        assert is_valid_cpt_format("") is False

    def test_radiology_range(self):
        assert is_radiology_cpt_range("74177") is True  # CT
        assert is_radiology_cpt_range("70553") is True  # MRI
        assert is_radiology_cpt_range("78816") is True  # PET
        assert is_radiology_cpt_range("99213") is False  # E&M, not radiology
        assert is_radiology_cpt_range("36415") is False  # Lab, not radiology


class TestRARCCodes:
    def test_has_common_codes(self):
        assert len(COMMON_RARC_CODES) >= 30
        assert "MA01" in COMMON_RARC_CODES
        assert "N1" in COMMON_RARC_CODES

    def test_descriptions(self):
        assert "appeal" in COMMON_RARC_CODES["N1"].lower()


class TestDTMQualifiers:
    def test_service_date_qualifiers(self):
        assert "232" in DTM_QUALIFIER_CODES
        assert "233" in DTM_QUALIFIER_CODES
        assert "472" in DTM_QUALIFIER_CODES


# ============================================================
# VALIDATION FUNCTION TESTS
# ============================================================

class TestValidateERAClaim:
    def test_valid_claim(self):
        claim = {
            "claim_status": "1",
            "cas_group_code": "CO",
            "cas_reason_code": "45",
            "cpt_code": "74177",
            "billed_amount": 1000,
            "paid_amount": 800,
        }
        results = validate_era_claim_line(claim)
        errors = [r for r in results if r.severity == "ERROR"]
        assert len(errors) == 0

    def test_invalid_claim_status(self):
        claim = {"claim_status": "99"}
        results = validate_era_claim_line(claim)
        errors = [r for r in results if not r.valid and r.severity == "ERROR"]
        assert any("claim_status" in r.field for r in errors)

    def test_invalid_cas_group(self):
        claim = {"cas_group_code": "ZZ"}
        results = validate_era_claim_line(claim)
        warnings = [r for r in results if r.severity == "WARNING"]
        assert any("cas_group_code" in r.field for r in warnings)

    def test_unknown_carc_code(self):
        claim = {"cas_reason_code": "9999"}
        results = validate_era_claim_line(claim)
        warnings = [r for r in results if r.severity == "WARNING"]
        assert any("cas_reason_code" in r.field for r in warnings)

    def test_known_carc_code_no_warning(self):
        claim = {"cas_reason_code": "45"}
        results = validate_era_claim_line(claim)
        warnings = [r for r in results if r.severity == "WARNING" and "cas_reason_code" in r.field]
        assert len(warnings) == 0

    def test_invalid_cpt_format(self):
        claim = {"cpt_code": "1234"}
        results = validate_era_claim_line(claim)
        warnings = [r for r in results if r.severity == "WARNING" and "cpt_code" in r.field]
        assert len(warnings) == 1

    def test_non_radiology_cpt(self):
        claim = {"cpt_code": "99213"}  # E&M code
        results = validate_era_claim_line(claim)
        warnings = [r for r in results if r.severity == "WARNING" and "cpt_code" in r.field]
        assert any("outside radiology" in r.message for r in warnings)

    def test_hcpcs_level_ii_accepted(self):
        claim = {"cpt_code": "A0428"}
        results = validate_era_claim_line(claim)
        cpt_errors = [r for r in results if r.field == "cpt_code" and "not valid" in r.message]
        assert len(cpt_errors) == 0

    def test_payment_method_validation(self):
        claim = {"payment_method": "INVALID"}
        results = validate_era_claim_line(claim)
        warnings = [r for r in results if r.severity == "WARNING" and "payment_method" in r.field]
        assert len(warnings) == 1

    def test_valid_payment_method(self):
        claim = {"payment_method": "ACH"}
        results = validate_era_claim_line(claim)
        warnings = [r for r in results if r.severity == "WARNING" and "payment_method" in r.field]
        assert len(warnings) == 0

    def test_cas_adjustment_delta_check(self):
        claim = {
            "billed_amount": 1000,
            "paid_amount": 600,
            "cas_adjustment_amount": 100,  # Should be ~400
        }
        results = validate_era_claim_line(claim)
        info = [r for r in results if r.severity == "INFO" and "cas_adjustment_amount" in r.field]
        assert len(info) == 1

    def test_paid_exceeds_billed(self):
        claim = {"billed_amount": 500, "paid_amount": 600}
        results = validate_era_claim_line(claim)
        warnings = [r for r in results if r.severity == "WARNING" and "paid_amount" in r.field]
        assert len(warnings) == 1

    def test_new_claim_status_3_accepted(self):
        """Claim status 3 (tertiary) should be valid after expansion."""
        claim = {"claim_status": "3"}
        results = validate_era_claim_line(claim)
        errors = [r for r in results if r.severity == "ERROR"]
        assert len(errors) == 0

    def test_new_claim_status_5_accepted(self):
        """Claim status 5 (pended) should be valid after expansion."""
        claim = {"claim_status": "5"}
        results = validate_era_claim_line(claim)
        errors = [r for r in results if r.severity == "ERROR"]
        assert len(errors) == 0

    def test_filing_denial_info(self):
        """CARC 29 (timely filing expired) should produce INFO."""
        claim = {"cas_reason_code": "29"}
        results = validate_era_claim_line(claim)
        info = [r for r in results if r.severity == "INFO" and "filing" in r.message.lower()]
        assert len(info) == 1


class TestValidateERAPayment:
    def test_valid_payment(self):
        payment = {
            "payment_method": "CHK",
            "payment_amount": 1500.00,
            "payment_date": date(2023, 6, 15),
            "check_eft_number": "12345678",
        }
        results = validate_era_payment(payment)
        assert all(r.valid or r.severity == "WARNING" for r in results)
        errors = [r for r in results if not r.valid and r.severity == "ERROR"]
        assert len(errors) == 0

    def test_invalid_payment_method(self):
        payment = {"payment_method": "WIRE"}
        results = validate_era_payment(payment)
        warnings = [r for r in results if r.severity == "WARNING" and "payment_method" in r.field]
        assert len(warnings) == 1

    def test_negative_payment(self):
        payment = {"payment_amount": -100}
        results = validate_era_payment(payment)
        warnings = [r for r in results if r.severity == "WARNING" and "payment_amount" in r.field]
        assert len(warnings) == 1

    def test_future_date(self):
        payment = {"payment_date": date(2099, 1, 1)}
        results = validate_era_payment(payment)
        warnings = [r for r in results if r.severity == "WARNING" and "payment_date" in r.field]
        assert len(warnings) == 1


class TestValidateERAbatch:
    def test_batch_with_mixed_validity(self):
        claims = [
            {"claim_status": "1", "cpt_code": "74177", "cas_reason_code": "45"},
            {"claim_status": "99", "cpt_code": "1234"},
            {"claim_status": "4", "cpt_code": "99213", "cas_reason_code": "9999"},
        ]
        result = validate_era_batch(claims)
        assert result["total"] == 3
        assert result["errors"] >= 1
        assert len(result["unknown_carc_codes"]) >= 1
        assert "9999" in result["unknown_carc_codes"]
        assert "99213" in result["non_radiology_cpt_codes"]


class TestEnrichment:
    def test_enrich_carc(self):
        assert enrich_carc_description("1") == "Deductible amount"
        assert enrich_carc_description("45") is not None
        assert enrich_carc_description(None) is None

    def test_enrich_claim_status(self):
        assert "Primary" in enrich_claim_status_description("1")
        assert "Denied" in enrich_claim_status_description("4")
        assert enrich_claim_status_description(None) is None

    def test_enrich_cpt(self):
        desc = enrich_cpt_description("74177")
        assert desc is not None
        assert "CT" in desc.upper() or "abdomen" in desc.lower()
        assert enrich_cpt_description(None) is None


# ============================================================
# INTEGRATION: data_validation imports from public_code_tables
# ============================================================

class TestDataValidationImports:
    def test_claim_statuses_expanded(self):
        """VALID_CLAIM_STATUSES should have all standard codes now."""
        assert "3" in VALID_CLAIM_STATUSES
        assert "5" in VALID_CLAIM_STATUSES
        assert "25" in VALID_CLAIM_STATUSES

    def test_carc_codes_full(self):
        """COMMON_CAS_REASON_CODES should now be the full set."""
        assert len(COMMON_CAS_REASON_CODES) >= 200

    def test_payment_methods_expanded(self):
        """PAYMENT_METHODS should include single-char X12 codes."""
        assert "C" in PAYMENT_METHODS
        assert "D" in PAYMENT_METHODS

    def test_cpt_crosswalk_extended(self):
        """CPT_TO_MODALITY should have many more entries now."""
        assert len(CPT_TO_MODALITY) >= 100
        assert CPT_TO_MODALITY.get("70450") == "CT"
        assert CPT_TO_MODALITY.get("77065") == "MAMMO"
