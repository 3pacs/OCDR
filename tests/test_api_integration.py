"""End-to-end API integration tests for all sprint features."""

import json
import os
import tempfile
import unittest
from datetime import date

from app import create_app
from app.models import db, BillingRecord, EraPayment, EraClaimLine, Payer, FeeSchedule


# Minimal 835 EDI test data
TEST_835 = (
    "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *240115*1200*^*00501*000000001*0*P*:~"
    "GS*HP*SENDER*RECEIVER*20240115*1200*1*X*005010X221A1~"
    "ST*835*0001~"
    "BPR*I*500.00*C*ACH*CCP*01*999999999*DA*123456789**01*888888888*DA*987654321*20240115~"
    "TRN*1*EFT99999*1234567890~"
    "N1*PR*TEST PAYER~"
    "CLP*TEST001*1*500.00*500.00*0.00*MA~"
    "NM1*QC*1*DOE*JANE****MI*999999999~"
    "DTM*232*20240101~"
    "SVC*HC:70553*500.00*500.00~"
    "SE*9*0001~"
    "GE*1*1~"
    "IEA*1*000000001~"
)


class TestAPIEndpoints(unittest.TestCase):
    """Integration tests for all API endpoints."""

    def setUp(self):
        self.app = create_app(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            TESTING=True,
            UPLOAD_FOLDER=tempfile.mkdtemp(),
            EXPORT_FOLDER=tempfile.mkdtemp(),
            BACKUP_FOLDER=tempfile.mkdtemp(),
        )
        self.client = self.app.test_client()
        with self.app.app_context():
            self._seed_data()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _seed_data(self):
        """Seed test data."""
        # Payers (skip if already seeded)
        if not Payer.query.filter_by(code="M/M").first():
            db.session.add(Payer(code="M/M", display_name="Medicare", filing_deadline_days=365))
        if not Payer.query.filter_by(code="INS").first():
            db.session.add(Payer(code="INS", display_name="Insurance", filing_deadline_days=180, expected_has_secondary=True))

        # Fee schedule (skip if already seeded by _seed_default_fee_schedule)
        if not FeeSchedule.query.filter_by(payer_code="DEFAULT", modality="HMRI").first():
            db.session.add(FeeSchedule(payer_code="DEFAULT", modality="HMRI", expected_rate=750.0))
        if not FeeSchedule.query.filter_by(payer_code="DEFAULT", modality="CT").first():
            db.session.add(FeeSchedule(payer_code="DEFAULT", modality="CT", expected_rate=395.0))

        # Billing records
        for i in range(5):
            db.session.add(BillingRecord(
                patient_name=f"PATIENT_{i}",
                referring_doctor="DR. TEST",
                scan_type="BRAIN MRI",
                modality="HMRI",
                insurance_carrier="M/M",
                service_date=date(2024, 1, 10 + i),
                total_payment=750.0 if i < 3 else 0.0,
                primary_payment=750.0 if i < 3 else 0.0,
                gado_used=(i % 2 == 0),
                is_psma=(i == 4),
                description="PSMA PET" if i == 4 else "BRAIN MRI",
                denial_status="DENIED" if i >= 3 else None,
            ))

        db.session.commit()

    # ── Health & Dashboard ────────────────────────

    def test_health(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["record_count"], 5)

    def test_dashboard_stats(self):
        resp = self.client.get("/api/dashboard/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["total_records"], 5)
        self.assertGreater(data["total_revenue"], 0)

    # ── F-02: 835 ERA Upload ─────────────────────

    def test_era_upload(self):
        import io
        data = {"files": (io.BytesIO(TEST_835.encode()), "test.835")}
        resp = self.client.post("/api/era/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200)
        result = resp.get_json()
        self.assertEqual(result["total_payments"], 1)
        self.assertEqual(result["total_claims"], 1)
        self.assertEqual(result["results"][0]["status"], "success")

    def test_era_upload_no_files(self):
        resp = self.client.post("/api/era/upload")
        self.assertEqual(resp.status_code, 400)

    def test_era_stats(self):
        # Upload first
        import io
        self.client.post("/api/era/upload",
                         data={"files": (io.BytesIO(TEST_835.encode()), "test.835")},
                         content_type="multipart/form-data")
        resp = self.client.get("/api/era/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["total_payments"], 1)
        self.assertEqual(data["total_claims"], 1)

    def test_era_payments_list(self):
        resp = self.client.get("/api/era/payments")
        self.assertEqual(resp.status_code, 200)

    def test_era_claims_list(self):
        resp = self.client.get("/api/era/claims")
        self.assertEqual(resp.status_code, 200)

    def test_era_by_month(self):
        resp = self.client.get("/api/era/by-month")
        self.assertEqual(resp.status_code, 200)

    # ── F-03: Match Engine ───────────────────────

    def test_match_run(self):
        # Upload 835 first
        import io
        self.client.post("/api/era/upload",
                         data={"files": (io.BytesIO(TEST_835.encode()), "test.835")},
                         content_type="multipart/form-data")
        resp = self.client.post("/api/match/run", json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("total_processed", data)

    def test_match_results(self):
        resp = self.client.get("/api/match/results")
        self.assertEqual(resp.status_code, 200)

    # ── F-04: Denial Queue ───────────────────────

    def test_denial_queue(self):
        resp = self.client.get("/api/denials/queue")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertGreater(data["total"], 0)  # We seeded $0 claims

    def test_denial_appeal(self):
        # Get a denied claim
        resp = self.client.get("/api/denials/queue")
        items = resp.get_json()["items"]
        if items:
            bid = items[0]["id"]
            resp = self.client.post(f"/api/denials/{bid}/appeal")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["status"], "appealed")

    def test_denial_resolve(self):
        resp = self.client.get("/api/denials/queue")
        items = resp.get_json()["items"]
        if items:
            bid = items[0]["id"]
            resp = self.client.post(f"/api/denials/{bid}/resolve",
                                    json={"resolution": "RESOLVED", "payment_amount": 500.0})
            self.assertEqual(resp.status_code, 200)

    def test_denial_bulk_appeal(self):
        resp = self.client.get("/api/denials/queue")
        ids = [i["id"] for i in resp.get_json()["items"][:2]]
        resp = self.client.post("/api/denials/bulk-appeal", json={"ids": ids})
        self.assertEqual(resp.status_code, 200)

    # ── F-05/F-06/F-07 (pre-existing) ───────────

    def test_underpayments(self):
        resp = self.client.get("/api/underpayments")
        self.assertEqual(resp.status_code, 200)

    def test_filing_deadlines(self):
        resp = self.client.get("/api/filing-deadlines")
        self.assertEqual(resp.status_code, 200)

    def test_secondary_followup(self):
        resp = self.client.get("/api/secondary-followup")
        self.assertEqual(resp.status_code, 200)

    # ── F-10: Statements ─────────────────────────

    def test_statements_generate(self):
        resp = self.client.post("/api/statements/generate",
                                json={"physician_name": "DR. TEST", "year": 2024, "month": 1})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["physician_name"], "DR. TEST")
        self.assertGreater(data["line_count"], 0)

    def test_statements_list(self):
        resp = self.client.get("/api/statements")
        self.assertEqual(resp.status_code, 200)

    # ── F-11: Monitor ────────────────────────────

    def test_monitor_status(self):
        resp = self.client.get("/api/monitor/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["state"], "stopped")

    # ── F-13: PSMA ───────────────────────────────

    def test_psma_summary(self):
        resp = self.client.get("/api/psma")
        self.assertEqual(resp.status_code, 200)

    def test_psma_by_year(self):
        resp = self.client.get("/api/psma/by-year")
        self.assertEqual(resp.status_code, 200)

    # ── F-14: Gado ───────────────────────────────

    def test_gado_summary(self):
        resp = self.client.get("/api/gado")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertGreater(data["total_gado_claims"], 0)

    def test_gado_margin(self):
        resp = self.client.get("/api/gado/margin?cost_per_dose=50")
        self.assertEqual(resp.status_code, 200)

    # ── F-16: Denial Analytics ───────────────────

    def test_denial_analytics(self):
        resp = self.client.get("/api/denial-analytics")
        self.assertEqual(resp.status_code, 200)

    def test_denial_pareto(self):
        resp = self.client.get("/api/denial-analytics/pareto")
        self.assertEqual(resp.status_code, 200)

    def test_denial_trend(self):
        resp = self.client.get("/api/denial-analytics/trend")
        self.assertEqual(resp.status_code, 200)

    # ── F-17: Payments ───────────────────────────

    def test_payments_summary(self):
        resp = self.client.get("/api/payments")
        self.assertEqual(resp.status_code, 200)

    def test_payments_status(self):
        resp = self.client.get("/api/payments/status")
        self.assertEqual(resp.status_code, 200)

    # ── F-18: Export ─────────────────────────────

    def test_export_trigger(self):
        resp = self.client.post("/api/export/trigger")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["record_count"], 5)

    def test_export_csv_download(self):
        resp = self.client.get("/api/export/csv")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.content_type)

    # ── F-20: Backup ─────────────────────────────

    def test_backup_history(self):
        resp = self.client.get("/api/backup/history")
        self.assertEqual(resp.status_code, 200)

    # ── UI Pages ─────────────────────────────────

    def test_all_pages_render(self):
        pages = [
            "/", "/underpayments", "/denials", "/filing-deadlines",
            "/secondary", "/payers", "/physicians", "/duplicates",
            "/schedule", "/era-payments", "/match-review", "/denial-queue",
            "/psma", "/gado", "/denial-analytics", "/payment-reconciliation",
            "/statements", "/import", "/admin",
        ]
        for page in pages:
            resp = self.client.get(page)
            self.assertEqual(resp.status_code, 200, f"Page {page} returned {resp.status_code}")


if __name__ == "__main__":
    unittest.main()
