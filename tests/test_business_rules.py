"""Tests for ocdr.business_rules."""

import pytest
from datetime import date, timedelta
from decimal import Decimal

from ocdr.business_rules import (
    detect_cap_exceptions, expand_cap_line_items, detect_psma_flags,
    detect_missing_secondary, detect_filing_issues, recoverability_score,
    compute_match_score, detect_underpayments, detect_duplicates,
    detect_denials, check_insurance_caveats,
)


# ── BR-01: C.A.P Exception ──────────────────────────────────────────────

class TestCAPException:
    def test_cap_triple_detected(self):
        records = [
            {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
             "scan_type": "CHEST", "description": "C.A.P"},
            {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
             "scan_type": "ABDOMEN", "description": "C.A.P"},
            {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
             "scan_type": "PELVIS", "description": "C.A.P"},
        ]
        result = detect_cap_exceptions(records)
        assert all(r.get("is_cap_exception") for r in result)

    def test_non_cap_not_marked(self):
        records = [
            {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
             "scan_type": "HEAD", "description": "BRAIN"},
        ]
        result = detect_cap_exceptions(records)
        assert not result[0].get("is_cap_exception")


# ── C.A.P Line-Item Expansion ───────────────────────────────────────────

class TestCAPExpansion:
    def test_research_gets_three_items(self):
        record = {
            "patient_name": "SMITH, JOHN",
            "description": "C.A.P",
            "insurance_carrier": "",
        }
        items = expand_cap_line_items(record, is_research=True)
        assert len(items) == 3
        scan_types = {r["scan_type"] for r in items}
        assert scan_types == {"CHEST", "ABDOMEN", "PELVIS"}

    def test_standard_gets_two_items(self):
        record = {
            "patient_name": "SMITH, JOHN",
            "description": "C.A.P",
            "insurance_carrier": "M/M",
        }
        items = expand_cap_line_items(record, is_research=False)
        assert len(items) == 2
        scan_types = {r["scan_type"] for r in items}
        assert scan_types == {"CHEST", "A/P"}

    def test_non_cap_unchanged(self):
        record = {
            "patient_name": "SMITH, JOHN",
            "description": "BRAIN",
        }
        items = expand_cap_line_items(record)
        assert len(items) == 1
        assert items[0] is record


# ── BR-02: PSMA Detection ───────────────────────────────────────────────

class TestPSMADetection:
    def test_psma_in_description(self):
        records = [
            {"description": "PSMA PET/CT"},
            {"description": "BRAIN-GADO"},
        ]
        result = detect_psma_flags(records)
        assert result[0]["is_psma"] is True
        assert not result[1].get("is_psma")


# ── BR-04: Missing Secondary ────────────────────────────────────────────

class TestMissingSecondary:
    def test_mm_with_primary_no_secondary(self):
        records = [
            {"insurance_carrier": "M/M",
             "primary_payment": Decimal("500"),
             "secondary_payment": Decimal("0")},
        ]
        result = detect_missing_secondary(records)
        assert len(result) == 1

    def test_mm_with_both_payments(self):
        records = [
            {"insurance_carrier": "M/M",
             "primary_payment": Decimal("500"),
             "secondary_payment": Decimal("100")},
        ]
        result = detect_missing_secondary(records)
        assert len(result) == 0


# ── BR-05: Filing Deadlines ─────────────────────────────────────────────

class TestFilingDeadlines:
    def test_past_deadline(self):
        records = [
            {"insurance_carrier": "ONE CALL",
             "service_date": date(2024, 1, 1),
             "total_payment": Decimal("0")},
        ]
        past, warning = detect_filing_issues(records, as_of=date(2025, 6, 1))
        assert len(past) == 1
        assert past[0]["filing_status"] == "PAST_DEADLINE"

    def test_warning_30day(self):
        # ONE CALL has 90-day deadline
        service = date(2025, 6, 1)
        as_of = service + timedelta(days=65)  # 25 days before deadline
        records = [
            {"insurance_carrier": "ONE CALL",
             "service_date": service,
             "total_payment": Decimal("0")},
        ]
        past, warning = detect_filing_issues(records, as_of=as_of)
        assert len(warning) == 1
        assert warning[0]["filing_status"] == "WARNING_30DAY"

    def test_safe(self):
        records = [
            {"insurance_carrier": "M/M",
             "service_date": date(2025, 6, 1),
             "total_payment": Decimal("0")},
        ]
        past, warning = detect_filing_issues(records, as_of=date(2025, 6, 15))
        assert len(past) == 0
        assert len(warning) == 0


# ── BR-08: Recoverability Score ──────────────────────────────────────────

class TestRecoverabilityScore:
    def test_recent_high_value(self):
        score = recoverability_score(
            Decimal("2500"), date(2025, 6, 1), as_of=date(2025, 6, 15))
        assert score > 2000  # Should be close to full billed amount

    def test_old_claim(self):
        score = recoverability_score(
            Decimal("2500"), date(2024, 1, 1), as_of=date(2025, 6, 1))
        assert score < 1000  # Should be significantly reduced


# ── BR-09: Match Score ───────────────────────────────────────────────────

class TestMatchScore:
    def test_perfect_match(self):
        billing = {
            "patient_name": "SMITH, JOHN",
            "service_date": date(2025, 1, 15),
            "modality": "CT",
            "scan_type": "CHEST",
        }
        era = {
            "patient_name": "SMITH, JOHN",
            "service_date": date(2025, 1, 15),
            "modality": "CT",
            "scan_type": "CHEST",
        }
        result = compute_match_score(billing, era)
        assert result["score"] == 1.0
        assert len(result["mismatches"]) == 0

    def test_name_mismatch(self):
        billing = {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
                    "modality": "CT", "scan_type": "CHEST"}
        era = {"patient_name": "JONES, MARY", "service_date": date(2025, 1, 15),
               "modality": "CT", "scan_type": "CHEST"}
        result = compute_match_score(billing, era)
        assert result["score"] < 1.0
        assert result["name_sim"] < 0.85

    def test_date_mismatch(self):
        billing = {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
                    "modality": "CT", "scan_type": "CHEST"}
        era = {"patient_name": "SMITH, JOHN", "service_date": date(2025, 2, 15),
               "modality": "CT", "scan_type": "CHEST"}
        result = compute_match_score(billing, era)
        assert result["date_match"] == 0.0

    def test_modality_mismatch(self):
        billing = {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
                    "modality": "CT", "scan_type": "CHEST"}
        era = {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
               "modality": "PET", "scan_type": "CHEST"}
        result = compute_match_score(billing, era)
        assert result["modality_match"] == 0.0


# ── BR-11: Underpayment Detection ────────────────────────────────────────

class TestUnderpayments:
    def test_underpaid(self):
        records = [
            {"modality": "HMRI", "insurance_carrier": "DEFAULT",
             "total_payment": Decimal("300"), "is_psma": False,
             "gado_used": False},
        ]
        result = detect_underpayments(records)
        assert len(result) == 1
        assert result[0]["pct_of_expected"] < 0.80

    def test_adequately_paid(self):
        records = [
            {"modality": "HMRI", "insurance_carrier": "DEFAULT",
             "total_payment": Decimal("750"), "is_psma": False,
             "gado_used": False},
        ]
        result = detect_underpayments(records)
        assert len(result) == 0


# ── Duplicate Detection ──────────────────────────────────────────────────

class TestDuplicates:
    def test_duplicates_found(self):
        records = [
            {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
             "scan_type": "CHEST", "modality": "CT"},
            {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
             "scan_type": "CHEST", "modality": "CT"},
        ]
        result = detect_duplicates(records)
        assert len(result) == 1
        assert len(result[0]) == 2

    def test_cap_excluded(self):
        records = [
            {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
             "scan_type": "CHEST", "modality": "CT",
             "description": "C.A.P"},
            {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
             "scan_type": "ABDOMEN", "modality": "CT",
             "description": "C.A.P"},
            {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
             "scan_type": "PELVIS", "modality": "CT",
             "description": "C.A.P"},
        ]
        result = detect_duplicates(records)
        assert len(result) == 0  # C.A.P excluded from duplicate check


# ── Denial Detection ─────────────────────────────────────────────────────

class TestDenials:
    def test_zero_payment(self):
        records = [
            {"total_payment": Decimal("0")},
            {"total_payment": Decimal("500")},
        ]
        result = detect_denials(records)
        assert len(result) == 1


# ── Insurance Caveats ────────────────────────────────────────────────────

class TestInsuranceCaveats:
    def test_one_call(self):
        flags = check_insurance_caveats({"insurance_carrier": "ONE CALL"})
        assert any("ONE CALL" in f for f in flags)

    def test_comp(self):
        flags = check_insurance_caveats({"insurance_carrier": "COMP"})
        assert any("COMP" in f for f in flags)

    def test_no_flags(self):
        flags = check_insurance_caveats({"insurance_carrier": "M/M"})
        assert len(flags) == 0
