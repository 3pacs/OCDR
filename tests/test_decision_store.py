"""Tests for ocdr.decision_store — JSONL persistence layer."""

import json
import pytest
from pathlib import Path
from datetime import datetime

from ocdr import decision_store
from ocdr.config import DECISION_DIR


@pytest.fixture(autouse=True)
def isolated_decision_file(tmp_path, monkeypatch):
    """Redirect decision storage to a temp directory for each test."""
    test_dir = tmp_path / "decisions"
    test_dir.mkdir()
    test_file = test_dir / "decisions.jsonl"
    monkeypatch.setattr(decision_store, "DECISION_DIR", test_dir)
    monkeypatch.setattr(decision_store, "DECISION_HISTORY_PATH", test_file)
    # Also patch the imported config values used by _ensure_dir
    monkeypatch.setattr("ocdr.decision_store.DECISION_DIR", test_dir)
    monkeypatch.setattr("ocdr.decision_store.DECISION_HISTORY_PATH", test_file)
    return test_file


class TestRecordDecision:
    def test_creates_file_and_writes(self, isolated_decision_file):
        decision_store.record_decision({
            "claim_id": "CLM001",
            "user_decision": "APPROVE",
        })
        assert isolated_decision_file.exists()
        lines = isolated_decision_file.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["claim_id"] == "CLM001"
        assert data["user_decision"] == "APPROVE"
        assert "timestamp" in data

    def test_appends_multiple_decisions(self, isolated_decision_file):
        decision_store.record_decision({"claim_id": "A"})
        decision_store.record_decision({"claim_id": "B"})
        decision_store.record_decision({"claim_id": "C"})
        lines = isolated_decision_file.read_text().strip().split("\n")
        assert len(lines) == 3


class TestLoadDecisions:
    def test_load_empty(self, isolated_decision_file):
        assert decision_store.load_all_decisions() == []

    def test_load_all(self, isolated_decision_file):
        decision_store.record_decision({"claim_id": "A", "user_decision": "APPROVE"})
        decision_store.record_decision({"claim_id": "B", "user_decision": "REJECT"})
        decisions = decision_store.load_all_decisions()
        assert len(decisions) == 2
        assert decisions[0]["claim_id"] == "A"
        assert decisions[1]["claim_id"] == "B"

    def test_load_for_payer(self, isolated_decision_file):
        decision_store.record_decision({"payer": "M/M", "claim_id": "A"})
        decision_store.record_decision({"payer": "ONE CALL", "claim_id": "B"})
        decision_store.record_decision({"payer": "M/M", "claim_id": "C"})
        result = decision_store.load_decisions_for_payer("M/M")
        assert len(result) == 2
        assert all(d["payer"] == "M/M" for d in result)

    def test_load_for_payer_case_insensitive(self, isolated_decision_file):
        decision_store.record_decision({"payer": "M/M", "claim_id": "A"})
        result = decision_store.load_decisions_for_payer("m/m")
        assert len(result) == 1

    def test_load_for_payer_by_carrier(self, isolated_decision_file):
        decision_store.record_decision({"insurance_carrier": "INS", "claim_id": "A"})
        result = decision_store.load_decisions_for_payer("INS")
        assert len(result) == 1


class TestDecisionStats:
    def test_empty_stats(self, isolated_decision_file):
        stats = decision_store.get_decision_stats()
        assert stats["total"] == 0

    def test_stats_computation(self, isolated_decision_file):
        for _ in range(5):
            decision_store.record_decision({
                "user_decision": "APPROVE",
                "system_status": "AUTO_ACCEPT",
                "match_score": 0.98,
                "claim_paid": "500.00",
            })
        for _ in range(3):
            decision_store.record_decision({
                "user_decision": "APPROVE",
                "system_status": "REVIEW",
                "match_score": 0.88,
                "claim_paid": "300.00",
            })
        for _ in range(2):
            decision_store.record_decision({
                "user_decision": "REJECT",
                "system_status": "REVIEW",
                "match_score": 0.75,
                "claim_paid": "0",
            })
        decision_store.record_decision({
            "user_decision": "SKIP",
            "match_score": 0.60,
            "claim_paid": "200.00",
        })

        stats = decision_store.get_decision_stats()
        assert stats["total"] == 11
        assert stats["approved"] == 8
        assert stats["rejected"] == 2
        assert stats["skipped"] == 1
        assert stats["auto_accepted"] == 5
        assert stats["review_accepted"] == 3
        assert stats["review_rejected"] == 2
        assert stats["total_approved_amount"] == 3400.00  # 5*500 + 3*300
        assert stats["total_rejected_amount"] == 0.0
        assert stats["total_skipped_amount"] == 200.00
        assert stats["avg_score_approved"] > 0
        assert stats["avg_score_rejected"] > 0


class TestDuplicateCheck:
    def test_no_duplicate(self, isolated_decision_file):
        assert decision_store.check_duplicate_payment(
            "SMITH, JOHN", "2025-01-15", "CT"
        ) is None

    def test_duplicate_found(self, isolated_decision_file):
        decision_store.record_decision({
            "user_decision": "APPROVE",
            "billing_patient": "SMITH, JOHN",
            "billing_date": "2025-01-15",
            "billing_modality": "CT",
            "claim_paid": "500",
        })
        result = decision_store.check_duplicate_payment(
            "SMITH, JOHN", "2025-01-15", "CT"
        )
        assert result is not None
        assert result["claim_paid"] == "500"

    def test_rejected_not_duplicate(self, isolated_decision_file):
        decision_store.record_decision({
            "user_decision": "REJECT",
            "billing_patient": "SMITH, JOHN",
            "billing_date": "2025-01-15",
            "billing_modality": "CT",
        })
        assert decision_store.check_duplicate_payment(
            "SMITH, JOHN", "2025-01-15", "CT"
        ) is None


class TestSessionState:
    def test_save_and_load(self, tmp_path):
        state = {"era_file": "test.835", "next_index": 5, "session_id": "s1"}
        path = tmp_path / "pending" / "state.json"
        decision_store.save_session_state(state, path)
        loaded = decision_store.load_session_state(path)
        assert loaded["era_file"] == "test.835"
        assert loaded["next_index"] == 5

    def test_load_nonexistent(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        assert decision_store.load_session_state(path) is None
