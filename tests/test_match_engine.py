"""Tests for the Auto-Match Engine (F-03)."""

import unittest
from datetime import date

from app import create_app
from app.models import db, BillingRecord, EraClaimLine, EraPayment
from app.matching.match_engine import (
    normalize_name, name_similarity, date_match_score,
    modality_match_score, compute_match_score, run_matching,
    confirm_match, reject_match, get_match_results,
)


class TestNameNormalization(unittest.TestCase):
    """Test patient name normalization for matching."""

    def test_last_comma_first(self):
        self.assertEqual(normalize_name("SMITH, JOHN"), "SMITH JOHN")

    def test_first_last(self):
        self.assertEqual(normalize_name("JOHN SMITH"), "JOHN SMITH")

    def test_strips_titles(self):
        self.assertEqual(normalize_name("DR. SMITH, JOHN JR."), "SMITH JOHN")

    def test_removes_middle_initial(self):
        result = normalize_name("SMITH, JOHN M")
        self.assertEqual(result, "SMITH JOHN")

    def test_handles_whitespace(self):
        self.assertEqual(normalize_name("  SMITH ,  JOHN  "), "SMITH JOHN")

    def test_empty_and_none(self):
        self.assertEqual(normalize_name(""), "")
        self.assertEqual(normalize_name(None), "")

    def test_uppercase(self):
        self.assertEqual(normalize_name("smith, john"), "SMITH JOHN")


class TestNameSimilarity(unittest.TestCase):
    """Test fuzzy name similarity scoring."""

    def test_exact_match(self):
        self.assertAlmostEqual(name_similarity("SMITH, JOHN", "SMITH, JOHN"), 1.0)

    def test_format_difference(self):
        # "SMITH JOHN" vs "SMITH JOHN" after normalization — should be perfect
        score = name_similarity("SMITH, JOHN", "JOHN SMITH")
        self.assertGreater(score, 0.8)

    def test_different_names(self):
        score = name_similarity("SMITH, JOHN", "WILLIAMS, ROBERT")
        self.assertLess(score, 0.5)

    def test_close_names(self):
        score = name_similarity("SMITH, JOHN", "SMITH, JON")
        self.assertGreater(score, 0.8)


class TestDateMatchScore(unittest.TestCase):
    """Test date proximity scoring."""

    def test_exact_match(self):
        d = date(2024, 1, 15)
        self.assertEqual(date_match_score(d, d), 1.0)

    def test_one_day_off(self):
        self.assertEqual(date_match_score(date(2024, 1, 15), date(2024, 1, 16)), 0.8)

    def test_two_days_off(self):
        self.assertEqual(date_match_score(date(2024, 1, 15), date(2024, 1, 17)), 0.5)

    def test_three_days_off(self):
        self.assertEqual(date_match_score(date(2024, 1, 15), date(2024, 1, 18)), 0.2)

    def test_none_date(self):
        self.assertEqual(date_match_score(None, date(2024, 1, 15)), 0.0)


class TestModalityMatchScore(unittest.TestCase):
    """Test CPT to modality matching."""

    def test_mri_cpt_matches_hmri(self):
        self.assertEqual(modality_match_score("70553", "HMRI"), 1.0)

    def test_ct_cpt_matches_ct(self):
        self.assertEqual(modality_match_score("74177", "CT"), 1.0)

    def test_mismatch(self):
        self.assertEqual(modality_match_score("70553", "CT"), 0.0)

    def test_no_cpt(self):
        self.assertEqual(modality_match_score("", "HMRI"), 0.0)


class TestMatchEngine(unittest.TestCase):
    """Integration tests for the match engine with database."""

    def setUp(self):
        self.app = create_app(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            TESTING=True,
        )
        self.ctx = self.app.app_context()
        self.ctx.push()

        # Seed billing records
        self.billing1 = BillingRecord(
            patient_name="SMITH, JOHN",
            referring_doctor="DR. TEST",
            scan_type="BRAIN MRI",
            modality="HMRI",
            insurance_carrier="M/M",
            service_date=date(2024, 1, 15),
            total_payment=750.0,
        )
        self.billing2 = BillingRecord(
            patient_name="JONES, MARY",
            referring_doctor="DR. TEST",
            scan_type="CT ABDOMEN",
            modality="CT",
            insurance_carrier="INS",
            service_date=date(2024, 1, 20),
            total_payment=395.0,
        )
        db.session.add_all([self.billing1, self.billing2])
        db.session.commit()

        # Seed ERA payment + claims
        self.era_payment = EraPayment(
            filename="test.835",
            check_eft_number="CHK001",
            payment_amount=1145.0,
            payment_date=date(2024, 2, 1),
            payer_name="MEDICARE",
        )
        db.session.add(self.era_payment)
        db.session.flush()

        self.era_claim1 = EraClaimLine(
            era_payment_id=self.era_payment.id,
            claim_id="CLM001",
            claim_status="PROCESSED_PRIMARY",
            billed_amount=800.0,
            paid_amount=750.0,
            patient_name_835="SMITH, JOHN",
            service_date_835=date(2024, 1, 15),
            cpt_code="70553",
        )
        self.era_claim2 = EraClaimLine(
            era_payment_id=self.era_payment.id,
            claim_id="CLM002",
            claim_status="PROCESSED_PRIMARY",
            billed_amount=500.0,
            paid_amount=395.0,
            patient_name_835="JONES, MARY",
            service_date_835=date(2024, 1, 20),
            cpt_code="74177",
        )
        db.session.add_all([self.era_claim1, self.era_claim2])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_run_matching(self):
        result = run_matching()
        self.assertEqual(result["total_processed"], 2)
        self.assertEqual(result["auto_accepted"], 2)
        self.assertEqual(result["rejected"], 0)

        # Verify claim1 matched to billing1
        claim1 = EraClaimLine.query.get(self.era_claim1.id)
        self.assertEqual(claim1.matched_billing_id, self.billing1.id)
        self.assertGreaterEqual(claim1.match_confidence, 0.95)

    def test_confirm_match(self):
        run_matching()
        result = confirm_match(self.era_claim1.id)
        self.assertEqual(result["status"], "confirmed")
        claim = EraClaimLine.query.get(self.era_claim1.id)
        self.assertEqual(claim.match_confidence, 1.0)

    def test_reject_match(self):
        run_matching()
        result = reject_match(self.era_claim1.id)
        self.assertEqual(result["status"], "rejected")
        claim = EraClaimLine.query.get(self.era_claim1.id)
        self.assertIsNone(claim.matched_billing_id)

    def test_get_match_results(self):
        run_matching()
        results = get_match_results(status_filter="auto_accepted")
        self.assertEqual(results["total"], 2)
        self.assertTrue(len(results["items"]) > 0)


if __name__ == "__main__":
    unittest.main()
