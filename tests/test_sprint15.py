"""Tests for Sprint 15: rate limiting, auth enforcement, backup, health check,
and Topaz file classification.
"""
import os
import sys
import time
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.models import db, BillingRecord, ScheduleRecord, User


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret"
    AUTH_ENFORCEMENT = False  # Off by default for most tests


class AuthEnforcedConfig(TestConfig):
    AUTH_ENFORCEMENT = True


# ══════════════════════════════════════════════════════════════════
#  Topaz File Classification
# ══════════════════════════════════════════════════════════════════

class TestTopazClassifier:
    """Test Topaz file naming pattern classification."""

    def test_monthly_billing_file(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("JAN12025")
        assert result["category"] == "monthly_billing"
        assert result["is_monthly"] is True
        assert result["month"] == "JAN"
        assert result["year"] == 2025
        assert result["sequence"] == 1
        assert result["importance"] == "high"

    def test_monthly_billing_sequence_2(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("FEB22026")
        assert result["category"] == "monthly_billing"
        assert result["is_monthly"] is True
        assert result["month"] == "FEB"
        assert result["year"] == 2026
        assert result["sequence"] == 2

    def test_patient_master(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("patnt")
        assert result["category"] == "patient_master"
        assert result["importance"] == "high"
        assert result["is_monthly"] is False

    def test_doctor_list(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("doclst")
        assert result["category"] == "doctor_list"

    def test_insurance_list(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("inslst")
        assert result["category"] == "insurance_list"

    def test_cpt_list(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("cptlst")
        assert result["category"] == "cpt_list"
        assert result["importance"] == "high"

    def test_diagnosis_list(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("dxtlst")
        assert result["category"] == "diagnosis_list"

    def test_referring_list(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("reflst")
        assert result["category"] == "referring_list"

    def test_patient_notes(self):
        from app.import_engine.topaz_importer import classify_file
        for name in ["PtNote", "PtNote2", "PtHosp", "PtRMK"]:
            result = classify_file(name)
            assert result["category"] == "patient_notes", f"Failed for {name}"

    def test_schedule_files(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("schdlx2")
        assert result["category"] == "schedule"

    def test_daily_files(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("daily1")
        assert result["category"] == "daily"

    def test_requisition_files(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("req12")
        assert result["category"] == "requisitions"

    def test_system_executable_skipped(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("BASIC14.EXE")
        assert result["category"] == "system_executable"
        assert result["importance"] == "skip"

    def test_config_file_skipped(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("something.WN8")
        assert result["category"] == "system_config"
        assert result["importance"] == "skip"

    def test_unknown_file(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("random_unknown_file")
        assert result["category"] == "unknown"

    def test_hidden_file(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file(".gitkeep")
        assert result["category"] == "hidden"
        assert result["importance"] == "skip"

    def test_word_processing(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("WP5")
        assert result["category"] == "word_processing"

    def test_monthly_invalid_year(self):
        from app.import_engine.topaz_importer import classify_file
        result = classify_file("JAN10001")
        assert result["category"] == "unknown"  # Year 0001 is out of range

    def test_monthly_all_months(self):
        from app.import_engine.topaz_importer import classify_file
        months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                  "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
        for month in months:
            result = classify_file(f"{month}12024")
            assert result["category"] == "monthly_billing", f"Failed for {month}"
            assert result["month"] == month


class TestTopazDirectoryAnalysis:
    """Test Topaz directory scanning."""

    def test_analyze_empty_directory(self):
        from app.import_engine.topaz_importer import analyze_topaz_directory
        with tempfile.TemporaryDirectory() as d:
            results = analyze_topaz_directory(d)
            assert results == []

    def test_analyze_nonexistent_directory(self):
        from app.import_engine.topaz_importer import analyze_topaz_directory
        results = analyze_topaz_directory("/nonexistent/path")
        assert results == []

    def test_analyze_with_sample_files(self):
        from app.import_engine.topaz_importer import analyze_topaz_directory
        with tempfile.TemporaryDirectory() as d:
            # Create some sample files
            with open(os.path.join(d, "patnt"), "w") as f:
                f.write("SMITH, JOHN       12345  M/M\n" * 5)
            with open(os.path.join(d, "JAN12025"), "w") as f:
                f.write("DATA LINE 1 FOR BILLING\n" * 10)
            with open(os.path.join(d, "BASIC14.EXE"), "wb") as f:
                f.write(b"\x00" * 100)

            results = analyze_topaz_directory(d)
            assert len(results) == 3

            # High-priority files come first
            categories = [r.get("classification", {}).get("category") for r in results]
            # patnt and JAN12025 are high priority, EXE is skip
            assert "system_executable" in categories

    def test_summary_with_monthly_files(self):
        from app.import_engine.topaz_importer import get_topaz_summary
        with tempfile.TemporaryDirectory() as d:
            for name in ["JAN12024", "FEB12024", "MAR22024", "JAN12025"]:
                with open(os.path.join(d, name), "w") as f:
                    f.write("data\n")

            summary = get_topaz_summary(d)
            assert summary["file_count"] == 4
            assert summary["categories"]["monthly_billing"] == 4
            assert summary["monthly_date_range"]["earliest"] == "JAN 2024"
            assert summary["monthly_date_range"]["latest"] == "JAN 2025"

    def test_summary_nonexistent(self):
        from app.import_engine.topaz_importer import get_topaz_summary
        result = get_topaz_summary("/nonexistent")
        assert "error" in result


# ══════════════════════════════════════════════════════════════════
#  Rate Limiter Unit Tests
# ══════════════════════════════════════════════════════════════════

class TestRateLimiter:
    """Test the in-process rate limiter."""

    def test_parse_rate_minute(self):
        from app.infra.rate_limiter import _parse_rate
        max_req, window = _parse_rate("10/minute")
        assert max_req == 10
        assert window == 60

    def test_parse_rate_second(self):
        from app.infra.rate_limiter import _parse_rate
        max_req, window = _parse_rate("5/second")
        assert max_req == 5
        assert window == 1

    def test_parse_rate_hour(self):
        from app.infra.rate_limiter import _parse_rate
        max_req, window = _parse_rate("100/hour")
        assert max_req == 100
        assert window == 3600

    def test_parse_rate_invalid(self):
        from app.infra.rate_limiter import _parse_rate
        with pytest.raises(ValueError):
            _parse_rate("invalid")

    def test_parse_rate_invalid_period(self):
        from app.infra.rate_limiter import _parse_rate
        with pytest.raises(ValueError):
            _parse_rate("10/fortnight")

    def test_check_rate_allows_within_limit(self):
        from app.infra.rate_limiter import _check_rate
        key = "test:allow:" + str(time.monotonic())
        allowed, remaining, retry = _check_rate(key, 5, 60)
        assert allowed is True
        assert remaining == 4
        assert retry is None

    def test_check_rate_blocks_over_limit(self):
        from app.infra.rate_limiter import _check_rate
        key = "test:block:" + str(time.monotonic())
        for _ in range(3):
            _check_rate(key, 3, 60)
        allowed, remaining, retry = _check_rate(key, 3, 60)
        assert allowed is False
        assert remaining == 0
        assert retry is not None and retry > 0


# ══════════════════════════════════════════════════════════════════
#  Auth Decorators
# ══════════════════════════════════════════════════════════════════

class TestAuthDecorators:
    """Test auth_required and admin_required decorators."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        self.app = create_app(AuthEnforcedConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            yield
            db.session.remove()

    def test_unauthenticated_page_redirects_to_login(self):
        resp = self.client.get("/")
        assert resp.status_code == 302
        assert "/login" in resp.location

    def test_unauthenticated_api_returns_401(self):
        # API routes don't use auth_required directly (they go through
        # the global rate limiter), but admin endpoints should check
        resp = self.client.get("/api/admin/users")
        assert resp.status_code == 401

    def test_admin_page_redirects_unauthenticated(self):
        resp = self.client.get("/admin")
        assert resp.status_code == 302
        assert "/login" in resp.location

    def test_login_page_accessible(self):
        resp = self.client.get("/login")
        assert resp.status_code == 200

    def test_login_and_access_dashboard(self):
        # Login
        resp = self.client.post("/login", data={
            "username": "admin",
            "password": "admin",
        }, follow_redirects=False)
        assert resp.status_code == 302

        # Now access dashboard
        resp = self.client.get("/")
        assert resp.status_code == 200

    def test_non_admin_cannot_access_admin_page(self):
        # Create a non-admin user
        with self.app.app_context():
            user = User(username="viewer", role="viewer")
            user.set_password("viewerpass")
            db.session.add(user)
            db.session.commit()

        # Login as viewer
        self.client.post("/login", data={
            "username": "viewer",
            "password": "viewerpass",
        })

        # Try to access admin page
        resp = self.client.get("/admin")
        assert resp.status_code == 302  # Redirected away from admin

    def test_auth_not_enforced_when_disabled(self):
        """With AUTH_ENFORCEMENT=False, all pages are accessible."""
        app = create_app(TestConfig)  # AUTH_ENFORCEMENT = False
        client = app.test_client()
        with app.app_context():
            resp = client.get("/")
            assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════
#  Health Check Enhancement
# ══════════════════════════════════════════════════════════════════

class TestHealthCheck:
    """Test enhanced health check endpoint."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            yield
            db.session.remove()

    def test_health_returns_200(self):
        resp = self.client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"

    def test_health_includes_journal_mode(self):
        resp = self.client.get("/api/health")
        data = resp.get_json()
        assert "journal_mode" in data

    def test_health_includes_auth_status(self):
        resp = self.client.get("/api/health")
        data = resp.get_json()
        assert "auth_enforced" in data
        assert data["auth_enforced"] is False  # TestConfig has it off

    def test_health_includes_backup_info(self):
        resp = self.client.get("/api/health")
        data = resp.get_json()
        assert "backup" in data

    def test_health_includes_disk_info(self):
        resp = self.client.get("/api/health")
        data = resp.get_json()
        assert "disk" in data

    def test_health_includes_counts(self):
        resp = self.client.get("/api/health")
        data = resp.get_json()
        assert "record_count" in data
        assert "era_count" in data
        assert "schedule_count" in data
        assert "table_count" in data


# ══════════════════════════════════════════════════════════════════
#  Topaz API Endpoints
# ══════════════════════════════════════════════════════════════════

class TestTopazAPI:
    """Test Topaz analysis API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            yield
            db.session.remove()

    def test_topaz_summary_missing_dir(self):
        resp = self.client.get("/api/topaz/summary?path=/nonexistent/path")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "error" in data

    def test_topaz_analyze_empty(self):
        with tempfile.TemporaryDirectory() as d:
            resp = self.client.get(f"/api/topaz/analyze?path={d}")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["total"] == 0

    def test_topaz_analyze_with_files(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "patnt"), "w") as f:
                f.write("TEST DATA\n" * 5)
            resp = self.client.get(f"/api/topaz/analyze?path={d}")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["total"] == 1

    def test_topaz_analyze_filter_category(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "patnt"), "w") as f:
                f.write("TEST\n")
            with open(os.path.join(d, "doclst"), "w") as f:
                f.write("TEST\n")
            resp = self.client.get(f"/api/topaz/analyze?path={d}&category=patient_master")
            data = resp.get_json()
            assert data["total"] == 1

    def test_topaz_file_detail_not_found(self):
        resp = self.client.get("/api/topaz/file/nonexistent?path=/tmp")
        assert resp.status_code == 404

    def test_topaz_file_detail(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "testfile"), "w") as f:
                f.write("LINE1 DATA HERE\n" * 10)
            resp = self.client.get(f"/api/topaz/file/testfile?path={d}")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "encoding" in data
            assert "hex_dump" in data
            assert "classification" in data
            assert data["line_count"] == 10


# ══════════════════════════════════════════════════════════════════
#  Backup API
# ══════════════════════════════════════════════════════════════════

class TestBackupAPI:
    """Test backup endpoints."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            yield
            db.session.remove()

    def test_backup_history(self):
        resp = self.client.get("/api/backup/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "backups" in data
        assert "total" in data

    def test_backup_status(self):
        resp = self.client.get("/api/backup/status")
        assert resp.status_code == 200

    def test_backup_verify_not_found(self):
        resp = self.client.get("/api/backup/verify/nonexistent.db")
        assert resp.status_code == 404
