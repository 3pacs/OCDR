"""Tests for Smart Matching features (SM-01 through SM-12).

Tests match memory, weight optimization, name aliases, CPT learning,
date curves, denial learning, payment patterns, import learning,
normalization, calibration, and API endpoints.
"""

import unittest
from datetime import date, datetime, timedelta

from app import create_app
from app.models import (
    db, BillingRecord, EraPayment, EraClaimLine, FeeSchedule,
    MatchOutcome, NameAlias, LearnedWeights, LearnedCptModality,
    DenialOutcome, ColumnAliasLearned, NormalizationLearned,
)


class SmartMatchingTestBase(unittest.TestCase):
    """Base class with app context and test data helpers."""

    def setUp(self):
        self.app = create_app(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            TESTING=True,
        )
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _add_billing(self, name="SMITH JOHN", carrier="BCBS", modality="HMRI",
                     service_date=None, total_payment=500.0, **kw):
        rec = BillingRecord(
            patient_name=name, referring_doctor="DR TEST",
            scan_type="MRI BRAIN", insurance_carrier=carrier,
            modality=modality, service_date=service_date or date(2024, 6, 15),
            total_payment=total_payment, **kw,
        )
        db.session.add(rec)
        db.session.flush()
        return rec

    def _add_era_claim(self, name="SMITH, JOHN", cpt="70553", service_date=None,
                       billing_id=None, confidence=None):
        era = EraPayment(filename="test.835", payment_amount=500.0)
        db.session.add(era)
        db.session.flush()
        claim = EraClaimLine(
            era_payment_id=era.id, patient_name_835=name,
            service_date_835=service_date or date(2024, 6, 15),
            cpt_code=cpt, billed_amount=600.0, paid_amount=500.0,
            matched_billing_id=billing_id, match_confidence=confidence,
        )
        db.session.add(claim)
        db.session.flush()
        return claim


class TestMatchOutcomeTracking(SmartMatchingTestBase):
    """SM-01a: Match outcome recording."""

    def test_record_confirmed_outcome(self):
        from app.matching.match_memory import record_outcome
        billing = self._add_billing()
        claim = self._add_era_claim(billing_id=billing.id, confidence=0.92)
        db.session.commit()

        oid = record_outcome(
            claim.id, billing.id, "CONFIRMED",
            original_score=0.92, name_score=0.95, date_score=1.0, modality_score=1.0,
            carrier="BCBS", modality="HMRI",
        )
        self.assertIsNotNone(oid)
        outcome = db.session.get(MatchOutcome, oid)
        self.assertEqual(outcome.action, "CONFIRMED")
        self.assertEqual(outcome.carrier, "BCBS")

    def test_record_rejected_outcome(self):
        from app.matching.match_memory import record_outcome
        billing = self._add_billing()
        claim = self._add_era_claim()
        db.session.commit()

        oid = record_outcome(claim.id, billing.id, "REJECTED", original_score=0.45)
        outcome = db.session.get(MatchOutcome, oid)
        self.assertEqual(outcome.action, "REJECTED")

    def test_get_outcomes(self):
        from app.matching.match_memory import record_outcome, get_outcomes
        billing = self._add_billing()
        claim = self._add_era_claim()
        db.session.commit()

        record_outcome(claim.id, billing.id, "CONFIRMED", carrier="BCBS")
        outcomes = get_outcomes(carrier="BCBS")
        self.assertEqual(len(outcomes), 1)

    def test_get_outcome_stats(self):
        from app.matching.match_memory import record_outcome, get_outcome_stats
        billing = self._add_billing()
        claim = self._add_era_claim()
        db.session.commit()

        record_outcome(claim.id, billing.id, "CONFIRMED", carrier="BCBS")
        stats = get_outcome_stats()
        self.assertEqual(stats["total_outcomes"], 1)


class TestNameAliases(SmartMatchingTestBase):
    """SM-04: Name alias learning and lookup."""

    def test_alias_stored_on_low_name_score(self):
        """Aliases are stored when name score is low and match is confirmed."""
        billing = self._add_billing(name="WILLIAMS BILL")
        claim = self._add_era_claim(name="WILLIAMS, WILLIAM", billing_id=billing.id)
        db.session.commit()

        from app.matching.match_memory import record_outcome
        record_outcome(
            claim.id, billing.id, "CONFIRMED",
            name_score=0.70, carrier="BCBS",
        )
        alias = NameAlias.query.first()
        self.assertIsNotNone(alias)

    def test_alias_not_stored_high_score(self):
        """Aliases are NOT stored when name score is already high."""
        billing = self._add_billing(name="SMITH JOHN")
        claim = self._add_era_claim(name="SMITH, JOHN", billing_id=billing.id)
        db.session.commit()

        from app.matching.match_memory import record_outcome
        record_outcome(
            claim.id, billing.id, "CONFIRMED",
            name_score=0.98, carrier="BCBS",
        )
        self.assertEqual(NameAlias.query.count(), 0)

    def test_alias_count_increments(self):
        """Repeated confirmations increment the match count."""
        billing = self._add_billing(name="WILLIAMS BILL")
        claim1 = self._add_era_claim(name="WILLIAMS, WILLIAM", billing_id=billing.id)
        claim2 = self._add_era_claim(name="WILLIAMS, WILLIAM", billing_id=billing.id)
        db.session.commit()

        from app.matching.match_memory import record_outcome
        record_outcome(claim1.id, billing.id, "CONFIRMED", name_score=0.70)
        record_outcome(claim2.id, billing.id, "CONFIRMED", name_score=0.70)
        alias = NameAlias.query.first()
        self.assertEqual(alias.match_count, 2)

    def test_alias_lookup_boosts_score(self):
        """Name similarity returns 1.0 when alias pair is found."""
        from app.matching.match_engine import name_similarity, normalize_name

        # Alias keys must use normalized (sorted) names
        n1 = normalize_name("SMITH, BILL")    # "BILL SMITH"
        n2 = normalize_name("SMITH, WILLIAM") # "SMITH WILLIAM"
        a, b = (n1, n2) if n1 <= n2 else (n2, n1)
        alias_lookup = {a: {b}}
        score = name_similarity("SMITH, BILL", "SMITH, WILLIAM", alias_lookup=alias_lookup)
        self.assertEqual(score, 1.0)

    def test_alias_lookup_without_match(self):
        """Normal fuzzy matching when no alias exists."""
        from app.matching.match_engine import name_similarity
        score = name_similarity("SMITH, BILL", "JONES, BOB", alias_lookup={})
        self.assertLess(score, 0.5)

    def test_build_alias_lookup(self):
        """Build alias lookup dict from database."""
        db.session.add(NameAlias(name_a="DOE JANE", name_b="DOE JANET", match_count=3))
        db.session.commit()

        from app.matching.match_memory import build_alias_lookup
        lookup = build_alias_lookup(min_count=2)
        self.assertIn("DOE JANET", lookup.get("DOE JANE", set()))


class TestWeightOptimizer(SmartMatchingTestBase):
    """SM-01b, SM-02: Weight and threshold optimization."""

    def _add_many_outcomes(self, n=60, carrier="BCBS"):
        """Add n outcomes with realistic score distributions."""
        billing = self._add_billing(carrier=carrier)
        for i in range(n):
            claim = self._add_era_claim(billing_id=billing.id)
            # Alternate confirmed/rejected with different score patterns
            if i % 3 == 0:  # ~33% rejected with low scores
                action = "REJECTED"
                ns, ds, ms, total = 0.3, 0.0, 0.0, 0.15
            else:  # ~66% confirmed with high scores
                action = "CONFIRMED"
                ns, ds, ms = 0.95, 1.0, 1.0
                total = 0.50 * ns + 0.30 * ds + 0.20 * ms
            db.session.add(MatchOutcome(
                era_claim_id=claim.id, billing_record_id=billing.id,
                action=action, original_score=total,
                name_score=ns, date_score=ds, modality_score=ms,
                carrier=carrier, modality="HMRI",
            ))
        db.session.commit()

    def test_optimize_weights_insufficient_data(self):
        from app.matching.weight_optimizer import optimize_weights
        result = optimize_weights(carrier="BCBS")
        self.assertIsNone(result)

    def test_optimize_weights_with_data(self):
        self._add_many_outcomes(60, "BCBS")
        from app.matching.weight_optimizer import optimize_weights
        result = optimize_weights(carrier="BCBS")
        self.assertIsNotNone(result)
        # Weights should sum to ~1.0
        total = result["name_weight"] + result["date_weight"] + result["modality_weight"]
        self.assertAlmostEqual(total, 1.0, places=2)
        self.assertGreaterEqual(result["sample_size"], 60)

    def test_optimize_thresholds_with_data(self):
        self._add_many_outcomes(60, "BCBS")
        from app.matching.weight_optimizer import optimize_thresholds
        result = optimize_thresholds(carrier="BCBS")
        self.assertIsNotNone(result)
        self.assertGreater(result["auto_accept_threshold"], result["review_threshold"])

    def test_store_and_retrieve_weights(self):
        self._add_many_outcomes(60, "BCBS")
        from app.matching.weight_optimizer import update_learned_weights, get_learned_weights
        update_learned_weights(carrier="BCBS")
        weights = get_learned_weights(carrier="BCBS")
        self.assertEqual(weights["source"], "learned:BCBS:any")
        self.assertGreaterEqual(weights["sample_size"], 50)

    def test_get_defaults_when_no_data(self):
        from app.matching.weight_optimizer import get_learned_weights
        weights = get_learned_weights(carrier="UNKNOWN")
        self.assertEqual(weights["source"], "default")
        self.assertEqual(weights["name_weight"], 0.50)

    def test_reset_weights(self):
        self._add_many_outcomes(60, "BCBS")
        from app.matching.weight_optimizer import update_learned_weights, reset_learned_weights
        update_learned_weights(carrier="BCBS")
        self.assertEqual(LearnedWeights.query.count(), 1)
        reset_learned_weights(carrier="BCBS")
        self.assertEqual(LearnedWeights.query.count(), 0)


class TestSmartMatchEngine(SmartMatchingTestBase):
    """SM-01c, SM-02b, SM-04b, SM-05b, SM-06b: Integrated smart match engine."""

    def test_compute_score_with_weights(self):
        from app.matching.match_engine import compute_match_score
        billing = self._add_billing()
        claim = self._add_era_claim(billing_id=billing.id)
        db.session.commit()

        # Custom weights
        weights = {"name_weight": 0.70, "date_weight": 0.20, "modality_weight": 0.10}
        total, ns, ds, ms = compute_match_score(claim, billing, weights=weights)
        self.assertGreater(total, 0)

    def test_date_match_extended_range(self):
        """Date matching now supports up to +-7 days."""
        from app.matching.match_engine import date_match_score
        d1 = date(2024, 6, 15)
        self.assertEqual(date_match_score(d1, d1), 1.0)
        self.assertEqual(date_match_score(d1, d1 + timedelta(days=1)), 0.8)
        self.assertEqual(date_match_score(d1, d1 + timedelta(days=2)), 0.5)
        self.assertGreater(date_match_score(d1, d1 + timedelta(days=3)), 0)
        self.assertGreater(date_match_score(d1, d1 + timedelta(days=7)), 0)
        self.assertEqual(date_match_score(d1, d1 + timedelta(days=8)), 0.0)

    def test_date_match_with_learned_curve(self):
        from app.matching.match_engine import date_match_score
        curve = {0: 1.0, 1: 0.9, 2: 0.7, 3: 0.4, 4: 0.2}
        d1 = date(2024, 6, 15)
        self.assertEqual(date_match_score(d1, d1 + timedelta(days=2), date_curve=curve), 0.7)

    def test_run_matching_performance_optimization(self):
        """run_matching should pre-load billing records (not N+1)."""
        from app.matching.match_engine import run_matching
        # Add data
        billing = self._add_billing()
        self._add_era_claim(name="SMITH, JOHN")
        db.session.commit()

        stats = run_matching()
        self.assertEqual(stats["total_processed"], 1)
        # Should have pass breakdown info
        self.assertIn("pass_1_exact", stats)

    def test_confirm_records_outcome(self):
        """confirm_match should record learning outcome."""
        billing = self._add_billing()
        claim = self._add_era_claim(billing_id=billing.id, confidence=0.92)
        db.session.commit()

        from app.matching.match_engine import confirm_match
        result = confirm_match(claim.id)
        self.assertEqual(result["status"], "confirmed")
        # Check outcome was recorded
        self.assertEqual(MatchOutcome.query.count(), 1)

    def test_reject_records_outcome(self):
        """reject_match should record learning outcome."""
        billing = self._add_billing()
        claim = self._add_era_claim(billing_id=billing.id, confidence=0.85)
        db.session.commit()

        from app.matching.match_engine import reject_match
        result = reject_match(claim.id)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(MatchOutcome.query.count(), 1)

    def test_confirm_validates_billing_id(self):
        """confirm_match should reject non-existent billing ID."""
        claim = self._add_era_claim()
        db.session.commit()

        from app.matching.match_engine import confirm_match
        result = confirm_match(claim.id, billing_id=99999)
        self.assertIn("error", result)

    def test_get_match_results_batch_load(self):
        """get_match_results should batch-load billing records."""
        from app.matching.match_engine import get_match_results
        billing = self._add_billing()
        self._add_era_claim(billing_id=billing.id, confidence=0.92)
        db.session.commit()

        results = get_match_results(page=1, per_page=10)
        self.assertEqual(results["total"], 1)
        item = results["items"][0]
        self.assertIn("matched_billing", item)


class TestDenialMemory(SmartMatchingTestBase):
    """SM-03: Denial recovery learning."""

    def test_record_denial_outcome(self):
        from app.revenue.denial_memory import record_denial_outcome
        billing = self._add_billing(total_payment=0, carrier="AETNA")
        db.session.commit()

        oid = record_denial_outcome(billing.id, "RECOVERED", 400.0)
        self.assertIsNotNone(oid)
        outcome = db.session.get(DenialOutcome, oid)
        self.assertEqual(outcome.outcome, "RECOVERED")
        self.assertEqual(outcome.recovered_amount, 400.0)

    def test_recovery_rates_insufficient_data(self):
        from app.revenue.denial_memory import get_recovery_rates
        rates = get_recovery_rates()
        self.assertEqual(len(rates), 0)

    def test_denial_pattern_detection(self):
        from app.revenue.denial_memory import detect_denial_patterns
        # Add 5 denials with same carrier/reason/modality
        for i in range(5):
            self._add_billing(
                name=f"PATIENT {i}", total_payment=0,
                carrier="CIGNA", modality="CT",
                denial_reason_code="49",
                service_date=date(2024, 6, i + 1),
            )
        db.session.commit()

        patterns = detect_denial_patterns()
        self.assertGreater(len(patterns), 0)
        self.assertEqual(patterns[0]["carrier"], "CIGNA")
        self.assertEqual(patterns[0]["count"], 5)
        self.assertIn("suggestion", patterns[0])


class TestDenialTrackerOptimized(SmartMatchingTestBase):
    """Performance-optimized denial tracker."""

    def test_denial_queue_with_fee_map(self):
        """Denial queue should pre-load fee schedule."""
        from app.revenue.denial_tracker import get_denial_queue
        db.session.add(FeeSchedule(payer_code="BCBS", modality="HMRI", expected_rate=800.0))
        self._add_billing(total_payment=0, carrier="BCBS", modality="HMRI",
                         service_date=date.today() - timedelta(days=30),
                         denial_status="DENIED")
        db.session.commit()

        result = get_denial_queue()
        self.assertEqual(result["total"], 1)
        self.assertGreater(result["items"][0]["recoverability_score"], 0)

    def test_resolve_records_learning_outcome(self):
        """resolve_denial should record denial outcome for learning."""
        from app.revenue.denial_tracker import resolve_denial
        billing = self._add_billing(total_payment=0)
        db.session.commit()

        resolve_denial(billing.id, "RESOLVED", payment_amount=400.0)
        self.assertEqual(DenialOutcome.query.count(), 1)

    def test_bulk_appeal_batch(self):
        """bulk_appeal should use batch query instead of N+1."""
        from app.revenue.denial_tracker import bulk_appeal
        ids = []
        for i in range(5):
            b = self._add_billing(name=f"PAT {i}", total_payment=0)
            ids.append(b.id)
        db.session.commit()

        result = bulk_appeal(ids)
        self.assertEqual(result["appealed"], 5)


class TestPaymentPatterns(SmartMatchingTestBase):
    """SM-07: Payment pattern learning."""

    def test_get_payment_patterns(self):
        from app.revenue.payment_patterns import get_payment_patterns
        for i in range(5):
            self._add_billing(
                name=f"PAT {i}", carrier="BCBS", modality="HMRI",
                total_payment=750 + i * 10,
                service_date=date.today() - timedelta(days=i),
            )
        db.session.commit()

        patterns = get_payment_patterns(days=90)
        self.assertGreater(len(patterns), 0)
        self.assertEqual(patterns[0]["carrier"], "BCBS")
        self.assertGreater(patterns[0]["avg_payment"], 0)

    def test_suggest_fee_updates(self):
        from app.revenue.payment_patterns import suggest_fee_updates
        db.session.add(FeeSchedule(payer_code="BCBS", modality="HMRI", expected_rate=500.0))
        for i in range(15):
            self._add_billing(
                name=f"PAT {i}", carrier="BCBS", modality="HMRI",
                total_payment=800.0,
                service_date=date.today() - timedelta(days=i),
            )
        db.session.commit()

        suggestions = suggest_fee_updates(min_count=10)
        self.assertGreater(len(suggestions), 0)
        self.assertGreater(suggestions[0]["diff_pct"], 15)

    def test_apply_fee_update(self):
        from app.revenue.payment_patterns import apply_fee_update
        db.session.add(FeeSchedule(payer_code="BCBS", modality="HMRI", expected_rate=500.0))
        db.session.commit()

        apply_fee_update("BCBS", "HMRI", 750.0)
        fs = FeeSchedule.query.filter_by(payer_code="BCBS", modality="HMRI").first()
        self.assertEqual(fs.expected_rate, 750.0)


class TestImportLearning(SmartMatchingTestBase):
    """SM-08, SM-09: Import column and normalization learning."""

    def test_learn_column_mapping(self):
        from app.import_engine.column_learner import learn_column_mapping, get_learned_aliases
        learn_column_mapping("Patient Full Name", "patient_name", "CSV")
        aliases = get_learned_aliases("CSV")
        self.assertIn("patient full name", aliases)
        self.assertEqual(aliases["patient full name"], "patient_name")

    def test_enhance_column_map(self):
        from app.import_engine.column_learner import learn_column_mapping, enhance_column_map
        learn_column_mapping("Pt Name", "patient_name")
        db.session.commit()

        headers = ["Pt Name", "Date", "Unknown Col"]
        col_map, unmapped = enhance_column_map(headers, {"date": "service_date"})
        self.assertEqual(col_map[0], "patient_name")  # Learned
        self.assertEqual(col_map[1], "service_date")   # Hardcoded
        self.assertEqual(len(unmapped), 1)

    def test_normalization_suggest(self):
        from app.import_engine.normalization_learner import suggest_normalization
        result = suggest_normalization("HIGH FIELD MR", "MODALITY")
        # Should be stored as pending
        pending = NormalizationLearned.query.first()
        self.assertIsNotNone(pending)
        self.assertFalse(pending.approved)

    def test_normalization_approve(self):
        from app.import_engine.normalization_learner import suggest_normalization, approve_normalization
        suggest_normalization("HIGHFIELD", "MODALITY")
        pending = NormalizationLearned.query.first()
        approve_normalization(pending.id, "HMRI")
        self.assertTrue(pending.approved)
        self.assertEqual(pending.normalized_value, "HMRI")

    def test_enhanced_normalize_modality(self):
        from app.import_engine.normalization_learner import enhanced_normalize_modality, approve_normalization
        # Add approved normalization
        db.session.add(NormalizationLearned(
            category="MODALITY", raw_value="MAGNET", normalized_value="HMRI", approved=True,
        ))
        db.session.commit()

        result = enhanced_normalize_modality("MAGNET")
        self.assertEqual(result, "HMRI")


class TestCalibration(SmartMatchingTestBase):
    """SM-10: Confidence calibration."""

    def _add_calibration_data(self, n=60):
        billing = self._add_billing()
        for i in range(n):
            claim = self._add_era_claim(billing_id=billing.id)
            score = 0.4 + (i / n) * 0.6  # Scores from 0.4 to 1.0
            action = "CONFIRMED" if score > 0.7 else "REJECTED"
            db.session.add(MatchOutcome(
                era_claim_id=claim.id, billing_record_id=billing.id,
                action=action, original_score=score,
            ))
        db.session.commit()

    def test_train_calibration_insufficient(self):
        from app.matching.calibration import train_calibration
        result = train_calibration()
        self.assertIsNone(result)

    def test_train_calibration_with_data(self):
        self._add_calibration_data(60)
        from app.matching.calibration import train_calibration
        result = train_calibration()
        self.assertIsNotNone(result)
        A, B = result
        self.assertIsInstance(A, float)
        self.assertIsInstance(B, float)

    def test_calibrate_score(self):
        from app.matching.calibration import calibrate_score
        params = (-5.0, 3.0)
        cal = calibrate_score(0.90, params)
        self.assertIsInstance(cal, float)
        self.assertGreater(cal, 0)
        self.assertLess(cal, 1)

    def test_calibrate_score_identity(self):
        from app.matching.calibration import calibrate_score
        self.assertEqual(calibrate_score(0.85, None), 0.85)


class TestPSMALearning(SmartMatchingTestBase):
    """SM-11: PSMA keyword expansion."""

    def test_detect_psma_base_keywords(self):
        from app.import_engine.validation import detect_psma
        self.assertTrue(detect_psma("PSMA PET/CT"))
        self.assertTrue(detect_psma("GA-68 PSMA"))
        self.assertTrue(detect_psma(None, "PYLARIFY PET"))
        self.assertFalse(detect_psma("Regular MRI"))

    def test_detect_psma_learned_keyword(self):
        from app.import_engine.validation import detect_psma
        db.session.add(NormalizationLearned(
            category="PSMA_KEYWORD", raw_value="FLOTUFOLASTAT",
            normalized_value="PSMA", approved=True,
        ))
        db.session.commit()
        self.assertTrue(detect_psma("FLOTUFOLASTAT PET"))


class TestXSSFix(SmartMatchingTestBase):
    """Verify XSS fix in physician statement HTML."""

    def test_html_escapes_physician_name(self):
        from app.revenue.physician_statements import generate_statement_html
        data = {
            "physician_name": "<script>alert(1)</script>",
            "period": "2024-01",
            "total_owed": 100.0, "total_paid": 0.0, "balance": 100.0,
            "line_items": [],
        }
        html = generate_statement_html(data)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_html_escapes_patient_name(self):
        from app.revenue.physician_statements import generate_statement_html
        data = {
            "physician_name": "Dr. Test",
            "period": "2024-01",
            "total_owed": 500.0, "total_paid": 0.0, "balance": 500.0,
            "line_items": [{
                "service_date": "2024-01-15",
                "patient_name": '<img src=x onerror="alert(1)">',
                "scan_type": "MRI", "modality": "HMRI",
                "insurance_carrier": "BCBS", "total_payment": 500.0,
            }],
        }
        html = generate_statement_html(data)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;img', html)


class TestSmartMatchingAPI(SmartMatchingTestBase):
    """Test all smart matching API endpoints."""

    def test_smart_outcomes_endpoint(self):
        r = self.client.get("/api/smart/outcomes")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("outcomes", data)
        self.assertIn("stats", data)

    def test_smart_weights_endpoint(self):
        r = self.client.get("/api/smart/weights")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("weights", data)

    def test_smart_weights_reset(self):
        r = self.client.post("/api/smart/weights/reset",
                             json={}, content_type="application/json")
        self.assertEqual(r.status_code, 200)

    def test_smart_aliases_endpoint(self):
        r = self.client.get("/api/smart/aliases")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("aliases", data)

    def test_smart_alias_delete(self):
        db.session.add(NameAlias(name_a="DOE JANE", name_b="DOE JANET", match_count=1))
        db.session.commit()
        alias = NameAlias.query.first()
        r = self.client.delete(f"/api/smart/aliases/{alias.id}")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(NameAlias.query.first())

    def test_smart_recovery_rates(self):
        r = self.client.get("/api/smart/recovery-rates")
        self.assertEqual(r.status_code, 200)

    def test_smart_payment_patterns(self):
        r = self.client.get("/api/smart/payment-patterns")
        self.assertEqual(r.status_code, 200)

    def test_smart_denial_patterns(self):
        r = self.client.get("/api/smart/denial-patterns")
        self.assertEqual(r.status_code, 200)

    def test_smart_cpt_map(self):
        r = self.client.get("/api/smart/cpt-map")
        self.assertEqual(r.status_code, 200)

    def test_smart_normalization_pending(self):
        r = self.client.get("/api/smart/normalization/pending")
        self.assertEqual(r.status_code, 200)

    def test_smart_normalization_approve(self):
        db.session.add(NormalizationLearned(
            category="MODALITY", raw_value="XMRI", normalized_value="HMRI",
        ))
        db.session.commit()
        n = NormalizationLearned.query.first()
        r = self.client.post("/api/smart/normalization/approve",
                             json={"id": n.id}, content_type="application/json")
        self.assertEqual(r.status_code, 200)

    def test_smart_column_mappings(self):
        r = self.client.get("/api/smart/column-mappings")
        self.assertEqual(r.status_code, 200)

    def test_smart_column_mapping_add(self):
        r = self.client.post("/api/smart/column-mappings",
                             json={"source_name": "Pt Name", "target_field": "patient_name"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ColumnAliasLearned.query.count(), 1)

    def test_smart_calibration(self):
        r = self.client.get("/api/smart/calibration")
        self.assertEqual(r.status_code, 200)

    def test_smart_analytics(self):
        r = self.client.get("/api/smart/analytics")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("outcome_stats", data)
        self.assertIn("accuracy_trend", data)

    def test_smart_dashboard(self):
        r = self.client.get("/api/smart/dashboard")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("match_outcomes", data)
        self.assertIn("features_active", data)

    def test_smart_matching_page(self):
        r = self.client.get("/smart-matching")
        self.assertEqual(r.status_code, 200)

    def test_fee_update_endpoint(self):
        db.session.add(FeeSchedule(payer_code="BCBS", modality="HMRI", expected_rate=500.0))
        db.session.commit()
        r = self.client.post("/api/smart/fee-update",
                             json={"carrier": "BCBS", "modality": "HMRI", "rate": 750},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)

    def test_fee_suggestions_endpoint(self):
        r = self.client.get("/api/smart/fee-suggestions")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
