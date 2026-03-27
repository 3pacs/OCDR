"""Tests for AI communication log and PHI encryption modules."""

import json
import os
import shutil
import tempfile

import pytest

# ── PHI Encryption Tests ──────────────────────────────────────────


class TestPhiEncrypt:
    """Tests for app.llm.phi_encrypt module."""

    def setup_method(self):
        # Reset module-level caches
        import app.llm.phi_encrypt as mod
        mod._fernet_instance = None
        mod._hmac_key = None

    def test_encrypt_phi_returns_prefixed_string(self):
        from app.llm.phi_encrypt import encrypt_phi
        result = encrypt_phi("SMITH, JOHN")
        assert result.startswith("ENC:") or result.startswith("HASH:")

    def test_encrypt_phi_empty_returns_empty(self):
        from app.llm.phi_encrypt import encrypt_phi
        assert encrypt_phi("") == ""
        assert encrypt_phi("   ") == ""

    def test_encrypt_decrypt_roundtrip(self):
        from app.llm.phi_encrypt import encrypt_phi, decrypt_phi
        original = "DOE, JANE"
        encrypted = encrypt_phi(original)
        if encrypted.startswith("ENC:"):
            decrypted = decrypt_phi(encrypted)
            assert decrypted == original
        else:
            # HMAC mode, cannot decrypt
            decrypted = decrypt_phi(encrypted)
            assert decrypted == encrypted  # returns unchanged

    def test_encrypt_record_encrypts_phi_fields(self):
        from app.llm.phi_encrypt import encrypt_record, PHI_FIELDS
        record = {
            "patient_name": "SMITH, JOHN",
            "modality": "CT",
            "service_date": "2026-01-15",
            "total_payment": 250.00,
        }
        result = encrypt_record(record)
        # PHI field should be encrypted
        assert result["patient_name"] != "SMITH, JOHN"
        assert result["patient_name"].startswith("ENC:") or result["patient_name"].startswith("HASH:")
        # Safe fields should pass through
        assert result["modality"] == "CT"
        assert result["service_date"] == "2026-01-15"
        assert result["total_payment"] == 250.00

    def test_decrypt_record(self):
        from app.llm.phi_encrypt import encrypt_record, decrypt_record
        record = {"patient_name": "SMITH, JOHN", "modality": "CT"}
        encrypted = encrypt_record(record)
        decrypted = decrypt_record(encrypted)
        # If Fernet is available, roundtrip should work
        if encrypted["patient_name"].startswith("ENC:"):
            assert decrypted["patient_name"] == "SMITH, JOHN"
        assert decrypted["modality"] == "CT"

    def test_redact_phi_from_text(self):
        from app.llm.phi_encrypt import redact_phi_from_text
        text = "Patient SMITH, JOHN has a CT scan"
        result = redact_phi_from_text(text)
        assert "SMITH" not in result
        assert "[REDACTED]" in result

    def test_redact_phi_handles_none(self):
        from app.llm.phi_encrypt import redact_phi_from_text
        assert redact_phi_from_text(None) is None
        assert redact_phi_from_text("") == ""

    def test_looks_like_name(self):
        from app.llm.phi_encrypt import _looks_like_name
        assert _looks_like_name("SMITH, JOHN") is True
        assert _looks_like_name("CT") is False
        assert _looks_like_name("") is False
        assert _looks_like_name("250.00") is False


# ── AI Log Tests ──────────────────────────────────────────────────


class TestAiLog:
    """Tests for app.llm.ai_log module."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        # Point the log module at our temp dir
        import app.llm.ai_log as mod
        mod._LOG_DIR = self.tmp_dir

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        import app.llm.ai_log as mod
        mod._LOG_DIR = None

    def test_log_chat_creates_file(self):
        from app.llm.ai_log import log_chat
        log_chat("What is revenue?", "Revenue is $100K", "template")
        path = os.path.join(self.tmp_dir, "chat_log.jsonl")
        assert os.path.exists(path)
        with open(path) as f:
            entry = json.loads(f.readline())
        assert entry["type"] == "chat"
        assert "revenue" in entry["data"]["question"].lower()

    def test_log_chat_redacts_phi(self):
        from app.llm.ai_log import log_chat
        log_chat(
            "Show records for SMITH, JOHN",
            "Found 5 records for SMITH, JOHN",
            "llm",
        )
        path = os.path.join(self.tmp_dir, "chat_log.jsonl")
        with open(path) as f:
            entry = json.loads(f.readline())
        # PHI should be redacted
        assert "SMITH, JOHN" not in entry["data"]["question"]
        assert "[REDACTED]" in entry["data"]["question"]

    def test_get_chat_history(self):
        from app.llm.ai_log import log_chat, get_chat_history
        for i in range(5):
            log_chat(f"Question {i}", f"Answer {i}", "template")
        history = get_chat_history(tail=3)
        assert len(history) == 3
        # Should be the last 3
        assert "Question 2" in history[0]["data"]["question"]

    def test_log_insight(self):
        from app.llm.ai_log import log_insight, get_insights
        log_insight("Revenue Drop", "Revenue decreased 20%", "warning", "revenue")
        insights = get_insights()
        assert len(insights) == 1
        assert insights[0]["data"]["title"] == "Revenue Drop"
        assert insights[0]["data"]["severity"] == "warning"

    def test_log_action(self):
        from app.llm.ai_log import log_action, get_actions
        log_action("Review claim", "Possible underpayment", "high")
        actions = get_actions()
        assert len(actions) == 1
        assert actions[0]["data"]["action"] == "Review claim"
        assert actions[0]["data"]["priority"] == "high"
        assert actions[0]["data"]["status"] == "pending"

    def test_get_actions_filter_by_status(self):
        from app.llm.ai_log import log_action, get_actions
        log_action("Action 1", "Reason 1", "normal")
        log_action("Action 2", "Reason 2", "high")
        # All pending by default
        all_actions = get_actions()
        assert len(all_actions) == 2
        pending = get_actions(status="pending")
        assert len(pending) == 2
        done = get_actions(status="completed")
        assert len(done) == 0

    def test_log_system_event(self):
        from app.llm.ai_log import log_system_event, get_system_events
        log_system_event("file_import", {"source_file": "test.835", "status": "success"})
        events = get_system_events()
        assert len(events) == 1
        assert events[0]["data"]["event"] == "file_import"

    def test_write_context_snapshot(self):
        from app.llm.ai_log import write_context_snapshot, read_context_snapshot
        # Will fail to build_context outside of app context, but should still create file
        snapshot = write_context_snapshot()
        assert "generated_at" in snapshot
        # Read it back
        read_back = read_context_snapshot()
        assert read_back["generated_at"] == snapshot["generated_at"]

    def test_write_ai_instructions(self):
        from app.llm.ai_log import write_ai_instructions
        path = write_ai_instructions()
        assert os.path.exists(path)
        with open(path) as f:
            content = f.read()
        assert "AI Log Communication Protocol" in content
        assert "PHI Protection" in content

    def test_action_encrypts_target_phi(self):
        from app.llm.ai_log import log_action, get_actions
        log_action(
            "Review claim",
            "Underpayment detected",
            target={"patient_name": "DOE, JANE", "modality": "CT"},
        )
        actions = get_actions()
        target = actions[0]["data"]["target"]
        # patient_name should be encrypted
        assert target["patient_name"] != "DOE, JANE"
        assert target["patient_name"].startswith("ENC:") or target["patient_name"].startswith("HASH:")
        # modality should be clear
        assert target["modality"] == "CT"


# ── API Endpoint Tests ────────────────────────────────────────────


class TestAiLogApi:
    """Tests for AI log API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_app(self, tmp_path):
        from app import create_app
        self.app = create_app(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            AI_LOG_FOLDER=str(tmp_path / "ai_logs"),
            PHI_ENCRYPTION_KEY="",
        )
        self.client = self.app.test_client()

        # Point the ai_log module at our temp dir
        with self.app.app_context():
            import app.llm.ai_log as mod
            mod._LOG_DIR = str(tmp_path / "ai_logs")
            os.makedirs(mod._LOG_DIR, exist_ok=True)

    def test_get_chat_log(self):
        with self.app.app_context():
            from app.llm.ai_log import log_chat
            log_chat("test q", "test a", "template")
        resp = self.client.get("/api/ai-log/chat")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["entries"]) == 1

    def test_get_insights(self):
        with self.app.app_context():
            from app.llm.ai_log import log_insight
            log_insight("Test", "Test insight", "info", "general")
        resp = self.client.get("/api/ai-log/insights")
        assert resp.status_code == 200
        assert len(resp.get_json()["entries"]) == 1

    def test_post_insight(self):
        resp = self.client.post("/api/ai-log/insight", json={
            "title": "External insight",
            "message": "From Claude Code",
            "severity": "info",
            "category": "system",
        })
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "logged"
        # Verify it's readable
        resp2 = self.client.get("/api/ai-log/insights")
        entries = resp2.get_json()["entries"]
        assert len(entries) == 1
        assert entries[0]["data"]["title"] == "External insight"

    def test_post_insight_validation(self):
        resp = self.client.post("/api/ai-log/insight", json={"title": "No message"})
        assert resp.status_code == 400

    def test_get_actions(self):
        with self.app.app_context():
            from app.llm.ai_log import log_action
            log_action("Test action", "Test reason")
        resp = self.client.get("/api/ai-log/actions")
        assert resp.status_code == 200
        assert len(resp.get_json()["entries"]) == 1

    def test_post_action(self):
        resp = self.client.post("/api/ai-log/action", json={
            "action": "Review denial",
            "reason": "Possible appeal opportunity",
            "priority": "high",
        })
        assert resp.status_code == 200
        # Check filtered by status
        resp2 = self.client.get("/api/ai-log/actions?status=pending")
        assert len(resp2.get_json()["entries"]) == 1

    def test_post_action_validation(self):
        resp = self.client.post("/api/ai-log/action", json={"action": "No reason"})
        assert resp.status_code == 400

    def test_get_system_events(self):
        with self.app.app_context():
            from app.llm.ai_log import log_system_event
            log_system_event("test_event")
        resp = self.client.get("/api/ai-log/system")
        assert resp.status_code == 200
        entries = resp.get_json()["entries"]
        # May have app_startup event + our test event
        assert len(entries) >= 1

    def test_get_context(self):
        resp = self.client.get("/api/ai-log/context")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "generated_at" in data

    def test_refresh_context(self):
        resp = self.client.get("/api/ai-log/context?refresh=true")
        assert resp.status_code == 200
        assert "generated_at" in resp.get_json()
