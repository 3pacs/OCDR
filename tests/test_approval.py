"""Tests for ocdr.approval — interactive 835 approval workflow.

Since the approval workflow reads from interactive input, tests focus on
the internal helpers (_match_all, _build_approved_record) and mock the
interactive portions.
"""

import pytest
from datetime import date
from decimal import Decimal

from ocdr import decision_store
from ocdr.approval import _match_all, _build_approved_record
from ocdr.business_rules import compute_match_score


@pytest.fixture(autouse=True)
def isolated_decisions(tmp_path, monkeypatch):
    """Redirect decision storage to temp directory."""
    test_dir = tmp_path / "decisions"
    test_dir.mkdir()
    test_file = test_dir / "decisions.jsonl"
    monkeypatch.setattr(decision_store, "DECISION_DIR", test_dir)
    monkeypatch.setattr(decision_store, "DECISION_HISTORY_PATH", test_file)
    monkeypatch.setattr("ocdr.decision_store.DECISION_DIR", test_dir)
    monkeypatch.setattr("ocdr.decision_store.DECISION_HISTORY_PATH", test_file)
    return test_file


# ── Match All ───────────────────────────────────────────────────────────

class TestMatchAll:
    def test_perfect_match(self):
        claims = [{
            "patient_name": "SMITH, JOHN",
            "service_date": date(2025, 1, 15),
            "modality": "CT",
            "scan_type": "CHEST",
        }]
        billing = [{
            "patient_name": "SMITH, JOHN",
            "service_date": date(2025, 1, 15),
            "modality": "CT",
            "scan_type": "CHEST",
        }]
        results = _match_all(claims, billing, compute_match_score)
        assert len(results) == 1
        assert results[0]["status"] == "AUTO_ACCEPT"
        assert results[0]["billing_record"] is not None
        assert results[0]["match_score"]["score"] >= 0.95

    def test_review_match(self):
        claims = [{
            "patient_name": "SMITH, JOHN",
            "service_date": date(2025, 1, 15),
            "modality": "CT",
            "scan_type": "CHEST",
        }]
        billing = [{
            "patient_name": "SMITH, J",
            "service_date": date(2025, 1, 15),
            "modality": "CT",
            "scan_type": "ABDOMEN",
        }]
        results = _match_all(claims, billing, compute_match_score)
        assert len(results) == 1
        assert results[0]["status"] in ("REVIEW", "UNMATCHED")

    def test_unmatched(self):
        claims = [{
            "patient_name": "SMITH, JOHN",
            "service_date": date(2025, 1, 15),
            "modality": "CT",
            "scan_type": "CHEST",
        }]
        billing = [{
            "patient_name": "TOTALLY DIFFERENT",
            "service_date": date(2024, 6, 1),
            "modality": "PET",
            "scan_type": "WHOLE BODY",
        }]
        results = _match_all(claims, billing, compute_match_score)
        assert len(results) == 1
        assert results[0]["status"] == "UNMATCHED"

    def test_multiple_claims_no_reuse(self):
        """Each billing record can only match one claim."""
        claims = [
            {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
             "modality": "CT", "scan_type": "CHEST"},
            {"patient_name": "JONES, MARY", "service_date": date(2025, 1, 15),
             "modality": "CT", "scan_type": "CHEST"},
        ]
        billing = [
            {"patient_name": "SMITH, JOHN", "service_date": date(2025, 1, 15),
             "modality": "CT", "scan_type": "CHEST"},
        ]
        results = _match_all(claims, billing, compute_match_score)
        assert len(results) == 2
        matched = [r for r in results if r["status"] != "UNMATCHED"]
        assert len(matched) == 1  # Only one match possible

    def test_empty_claims(self):
        results = _match_all([], [{"patient_name": "X"}], compute_match_score)
        assert results == []

    def test_empty_billing(self):
        claims = [{"patient_name": "SMITH", "service_date": date(2025, 1, 1),
                    "modality": "CT", "scan_type": "CHEST"}]
        results = _match_all(claims, [], compute_match_score)
        assert len(results) == 1
        assert results[0]["status"] == "UNMATCHED"


# ── Build Approved Record ───────────────────────────────────────────────

class TestBuildApprovedRecord:
    def test_merges_payment_data(self):
        claim = {
            "claim_id": "CLM001",
            "paid_amount": Decimal("600"),
            "payer_name": "BLUE CROSS",
            "payment_date": date(2025, 1, 15),
            "payment_method": "CHK",
            "cpt_codes": ["70553"],
            "billed_amount": Decimal("750"),
            "claim_status": "1",
            "check_eft_number": "12345",
        }
        billing = {
            "patient_name": "SMITH, JOHN",
            "service_date": date(2025, 1, 10),
            "modality": "HMRI",
            "scan_type": "HEAD",
            "source_row": 142,
            "insurance_carrier": "INS",
        }
        score_detail = {"score": 0.97}
        result = _build_approved_record(claim, billing, score_detail)

        assert result["patient_name"] == "SMITH, JOHN"
        assert result["primary_payment"] == Decimal("600")
        assert result["claim_id"] == "CLM001"
        assert result["payer_835"] == "BLUE CROSS"
        assert result["match_score"] == 0.97
        assert result["cpt_codes"] == "70553"
        assert result["total_payment"] == Decimal("600")
        assert "approval_timestamp" in result

    def test_total_payment_with_secondary(self):
        claim = {
            "paid_amount": Decimal("400"),
            "cpt_codes": [],
        }
        billing = {
            "secondary_payment": Decimal("100"),
        }
        result = _build_approved_record(claim, billing, {"score": 0.9})
        assert result["total_payment"] == Decimal("500")

    def test_zero_payment(self):
        claim = {
            "paid_amount": Decimal("0"),
            "cpt_codes": [],
        }
        billing = {}
        result = _build_approved_record(claim, billing, {"score": 0.8})
        assert result["primary_payment"] == Decimal("0")
        assert result["total_payment"] == Decimal("0")
