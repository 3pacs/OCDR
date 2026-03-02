"""Tests for ocdr.smart_reports — report generators."""

import pytest
from datetime import date
from decimal import Decimal

from ocdr import decision_store, smart_reports


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


def _seed_decisions(n_approve=10, n_reject=3, n_skip=1, payer="M/M"):
    """Helper to seed decision history with sample data."""
    for i in range(n_approve):
        decision_store.record_decision({
            "user_decision": "APPROVE",
            "system_status": "AUTO_ACCEPT" if i < 7 else "REVIEW",
            "match_score": 0.97 if i < 7 else 0.88,
            "claim_paid": "600.00",
            "payer": payer,
            "insurance_carrier": payer,
            "billing_modality": "CT",
            "mismatches": [],
        })
    for i in range(n_reject):
        decision_store.record_decision({
            "user_decision": "REJECT",
            "system_status": "REVIEW",
            "match_score": 0.75,
            "claim_paid": "0",
            "payer": payer,
            "insurance_carrier": payer,
            "billing_modality": "CT",
            "mismatches": ["Body part mismatch: 'ABDOMEN' vs 'A/P'"],
        })
    for i in range(n_skip):
        decision_store.record_decision({
            "user_decision": "SKIP",
            "match_score": 0.60,
            "claim_paid": "200.00",
            "payer": payer,
            "insurance_carrier": payer,
        })


# ── Report: Summary ─────────────────────────────────────────────────────

class TestReportSummary:
    def test_empty_decisions(self, capsys):
        result = smart_reports.report_summary()
        assert result["total"] == 0
        captured = capsys.readouterr()
        assert "No decisions" in captured.out

    def test_with_data(self, capsys):
        _seed_decisions()
        result = smart_reports.report_summary()
        assert result["total"] == 14
        assert result["approved"] == 10
        assert result["rejected"] == 3
        assert result["skipped"] == 1
        captured = capsys.readouterr()
        assert "Reconciliation Summary" in captured.out
        assert "Total claims reviewed" in captured.out


# ── Report: Payer ───────────────────────────────────────────────────────

class TestReportPayer:
    def test_empty(self, capsys):
        result = smart_reports.report_payer()
        assert result == {}

    def test_with_data(self, capsys):
        _seed_decisions(payer="M/M")
        _seed_decisions(n_approve=5, n_reject=1, n_skip=0, payer="ONE CALL")
        result = smart_reports.report_payer()
        assert "M/M" in result
        assert "ONE CALL" in result
        assert result["M/M"]["total"] == 14
        assert result["ONE CALL"]["approved"] == 5
        captured = capsys.readouterr()
        assert "Payer Analysis" in captured.out


# ── Report: Learning ────────────────────────────────────────────────────

class TestReportLearning:
    def test_not_enough_data(self, capsys):
        _seed_decisions(n_approve=3, n_reject=1, n_skip=0)
        result = smart_reports.report_learning()
        assert result == {}
        captured = capsys.readouterr()
        assert "Need at least 10" in captured.out

    def test_with_sufficient_data(self, capsys):
        _seed_decisions(n_approve=15, n_reject=5, n_skip=2, payer="M/M")
        result = smart_reports.report_learning()
        assert "threshold_recommendations" in result
        assert "synonym_suggestions" in result
        assert "payer_alias_suggestions" in result
        assert "scoring_insights" in result
        captured = capsys.readouterr()
        assert "Learning Insights" in captured.out

    def test_synonym_suggestions(self, capsys):
        # Seed decisions with body part mismatch patterns
        for i in range(12):
            decision_store.record_decision({
                "user_decision": "APPROVE",
                "system_status": "REVIEW",
                "match_score": 0.88,
                "claim_paid": "500",
                "payer": "M/M",
                "insurance_carrier": "M/M",
                "billing_modality": "CT",
                "mismatches": ["Body part mismatch: 'ABDOMEN' vs 'A/P'"
                               ] if i < 5 else [],
            })
        result = smart_reports.report_learning()
        # Should suggest A/P <-> ABDOMEN synonym
        has_synonym = any("ABDOMEN" in s and "A/P" in s
                         for s in result.get("synonym_suggestions", []))
        assert has_synonym

    def test_payer_alias_suggestions(self, capsys):
        for i in range(12):
            decision_store.record_decision({
                "user_decision": "APPROVE",
                "system_status": "REVIEW",
                "match_score": 0.88,
                "claim_paid": "500",
                "payer": "BCBS OF CA",
                "insurance_carrier": "INS",
                "billing_modality": "CT",
                "mismatches": [],
            })
        result = smart_reports.report_learning()
        has_alias = any("BCBS OF CA" in a
                       for a in result.get("payer_alias_suggestions", []))
        assert has_alias

    def test_scoring_insights(self, capsys):
        # Create decisions at different score buckets
        for _ in range(5):
            decision_store.record_decision({
                "user_decision": "APPROVE",
                "match_score": 0.95,
                "payer": "M/M",
                "insurance_carrier": "M/M",
                "billing_modality": "CT",
                "mismatches": [],
            })
        for _ in range(3):
            decision_store.record_decision({
                "user_decision": "REJECT",
                "match_score": 0.75,
                "payer": "M/M",
                "insurance_carrier": "M/M",
                "billing_modality": "CT",
                "mismatches": ["Name mismatch"],
            })
        # Need 10 total
        for _ in range(3):
            decision_store.record_decision({
                "user_decision": "APPROVE",
                "match_score": 0.85,
                "payer": "M/M",
                "insurance_carrier": "M/M",
                "billing_modality": "CT",
                "mismatches": [],
            })
        result = smart_reports.report_learning()
        assert len(result.get("scoring_insights", {})) > 0


# ── Report: Aging ───────────────────────────────────────────────────────

class TestReportAging:
    def test_empty_records(self, capsys):
        result = smart_reports.report_aging([], as_of=date(2025, 3, 1))
        assert result == []

    def test_unpaid_claims_by_band(self, capsys):
        records = [
            {
                "patient_name": "SMITH, JOHN",
                "service_date": date(2025, 2, 15),
                "total_payment": Decimal("0"),
                "modality": "CT",
                "insurance_carrier": "M/M",
                "is_psma": False,
                "gado_used": False,
            },
            {
                "patient_name": "JONES, MARY",
                "service_date": date(2025, 1, 1),
                "total_payment": Decimal("0"),
                "modality": "HMRI",
                "insurance_carrier": "M/M",
                "is_psma": False,
                "gado_used": False,
            },
            {
                "patient_name": "DOE, JANE",
                "service_date": date(2025, 2, 28),
                "total_payment": Decimal("500"),  # Paid — excluded
                "modality": "CT",
                "insurance_carrier": "M/M",
            },
        ]
        result = smart_reports.report_aging(records, as_of=date(2025, 3, 1))
        # SMITH should be in 0-30 band, JONES in 31-60
        assert len(result) >= 1
        # At least one band has claims
        total_claims = sum(r["claims"] for r in result)
        assert total_claims == 2  # Only 2 unpaid

    def test_past_deadline_flag(self, capsys):
        records = [
            {
                "patient_name": "OLD, CLAIM",
                "service_date": date(2023, 1, 1),
                "total_payment": Decimal("0"),
                "modality": "CT",
                "insurance_carrier": "M/M",
                "is_psma": False,
                "gado_used": False,
            },
        ]
        result = smart_reports.report_aging(records, as_of=date(2025, 3, 1))
        assert len(result) == 1
        assert result[0]["band"] == "365+ days"
        captured = capsys.readouterr()
        assert "PAST DEADLINE" in captured.out
