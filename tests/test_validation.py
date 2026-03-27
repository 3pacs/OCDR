"""Tests for shared validation module and import data correctness."""

import csv
import os
import tempfile
import unittest
from datetime import date, timedelta

from app import create_app
from app.models import db, BillingRecord
from app.import_engine.validation import (
    parse_date, parse_float, parse_bool, normalize_modality,
    normalize_carrier, detect_psma, compute_total_payment,
    build_dedup_set, is_duplicate, validate_billing_record,
)


class TestParseDate(unittest.TestCase):
    """Test date parsing with validation."""

    def test_mm_dd_yyyy(self):
        self.assertEqual(parse_date("01/15/2024"), date(2024, 1, 15))

    def test_yyyy_mm_dd(self):
        self.assertEqual(parse_date("2024-01-15"), date(2024, 1, 15))

    def test_mm_dd_yy(self):
        self.assertEqual(parse_date("01/15/24"), date(2024, 1, 15))

    def test_yyyymmdd(self):
        self.assertEqual(parse_date("20240115"), date(2024, 1, 15))

    def test_datetime_object(self):
        from datetime import datetime
        self.assertEqual(parse_date(datetime(2024, 1, 15, 10, 30)), date(2024, 1, 15))

    def test_date_object(self):
        self.assertEqual(parse_date(date(2024, 1, 15)), date(2024, 1, 15))

    def test_excel_serial(self):
        # Excel serial 45306 = 2024-01-15
        self.assertEqual(parse_date(45306), date(2024, 1, 15))

    def test_none(self):
        self.assertIsNone(parse_date(None))

    def test_empty_string(self):
        self.assertIsNone(parse_date(""))

    def test_garbage_string(self):
        self.assertIsNone(parse_date("not a date"))

    def test_rejects_too_old(self):
        """Dates before 1990 should be rejected."""
        self.assertIsNone(parse_date("01/01/1980"))

    def test_rejects_far_future(self):
        """Dates more than 1 year in the future should be rejected."""
        future = date.today() + timedelta(days=400)
        self.assertIsNone(parse_date(future.strftime("%m/%d/%Y")))

    def test_accepts_recent_past(self):
        """Recent dates should be accepted."""
        recent = date(2024, 6, 15)
        self.assertEqual(parse_date("06/15/2024"), recent)


class TestParseFloat(unittest.TestCase):
    """Test float parsing with validation."""

    def test_basic_float(self):
        self.assertEqual(parse_float("123.45"), 123.45)

    def test_with_dollar_sign(self):
        self.assertEqual(parse_float("$1,234.56"), 1234.56)

    def test_with_commas(self):
        self.assertEqual(parse_float("1,000.00"), 1000.0)

    def test_none(self):
        self.assertEqual(parse_float(None), 0.0)

    def test_empty_string(self):
        self.assertEqual(parse_float(""), 0.0)

    def test_negative_preserved(self):
        """Negative values preserved for refunds/adjustments."""
        self.assertEqual(parse_float("-100.00"), -100.0)

    def test_int_input(self):
        self.assertEqual(parse_float(750), 750.0)

    def test_float_input(self):
        self.assertEqual(parse_float(750.50), 750.50)

    def test_garbage(self):
        self.assertEqual(parse_float("abc"), 0.0)


class TestParseBool(unittest.TestCase):

    def test_y(self):
        self.assertTrue(parse_bool("Y"))

    def test_yes(self):
        self.assertTrue(parse_bool("yes"))

    def test_true(self):
        self.assertTrue(parse_bool("TRUE"))

    def test_one(self):
        self.assertTrue(parse_bool("1"))

    def test_gado(self):
        self.assertTrue(parse_bool("GADO"))

    def test_x(self):
        self.assertTrue(parse_bool("X"))

    def test_n(self):
        self.assertFalse(parse_bool("N"))

    def test_none(self):
        self.assertFalse(parse_bool(None))

    def test_empty(self):
        self.assertFalse(parse_bool(""))

    def test_bool_true(self):
        self.assertTrue(parse_bool(True))

    def test_bool_false(self):
        self.assertFalse(parse_bool(False))


class TestNormalizeModality(unittest.TestCase):

    def test_mri_to_hmri(self):
        self.assertEqual(normalize_modality("MRI"), "HMRI")

    def test_hmri(self):
        self.assertEqual(normalize_modality("HMRI"), "HMRI")

    def test_ct(self):
        self.assertEqual(normalize_modality("CT"), "CT")

    def test_cat_scan(self):
        self.assertEqual(normalize_modality("CAT SCAN"), "CT")

    def test_pet_ct(self):
        self.assertEqual(normalize_modality("PET/CT"), "PET")

    def test_bone_density(self):
        self.assertEqual(normalize_modality("BONE DENSITY"), "BONE")

    def test_dexa(self):
        self.assertEqual(normalize_modality("DEXA"), "BONE")

    def test_open_mri(self):
        self.assertEqual(normalize_modality("OPEN MRI"), "OPEN")

    def test_xray(self):
        self.assertEqual(normalize_modality("X-RAY"), "DX")

    def test_none_returns_none(self):
        self.assertIsNone(normalize_modality(None))

    def test_empty_returns_none(self):
        self.assertIsNone(normalize_modality(""))

    def test_unknown_passthrough(self):
        self.assertEqual(normalize_modality("FLUORO"), "FLUORO")

    def test_case_insensitive(self):
        self.assertEqual(normalize_modality("mri"), "HMRI")


class TestNormalizeCarrier(unittest.TestCase):

    def test_selfpay_variants(self):
        self.assertEqual(normalize_carrier("SELFPAY"), "SELF PAY")
        self.assertEqual(normalize_carrier("SELF-PAY"), "SELF PAY")
        self.assertEqual(normalize_carrier("CASH"), "SELF PAY")

    def test_medicare(self):
        self.assertEqual(normalize_carrier("MEDICARE"), "M/M")

    def test_medicaid(self):
        self.assertEqual(normalize_carrier("MEDICAID"), "M/M")

    def test_none_defaults_unknown(self):
        self.assertEqual(normalize_carrier(None), "UNKNOWN")

    def test_empty_defaults_unknown(self):
        self.assertEqual(normalize_carrier(""), "UNKNOWN")

    def test_other_passthrough(self):
        self.assertEqual(normalize_carrier("SOME UNKNOWN CARRIER"), "SOME UNKNOWN CARRIER")

    def test_case_preserved_for_unknown(self):
        self.assertEqual(normalize_carrier("Acme Health"), "ACME HEALTH")

    def test_commercial_insurance_maps_to_ins(self):
        self.assertEqual(normalize_carrier("BLUE CROSS"), "INS")
        self.assertEqual(normalize_carrier("Cigna"), "INS")
        self.assertEqual(normalize_carrier("ANTHEM"), "INS")

    def test_era_payer_fallback(self):
        self.assertEqual(normalize_carrier("CALIFORNIA PHYSICIANS SERVICE DBA BLUE SHIELD CA"), "INS")
        self.assertEqual(normalize_carrier("PROSPECT MEDICAL SYSTEMS"), "FAMILY")


class TestDetectPsma(unittest.TestCase):

    def test_psma_in_description(self):
        self.assertTrue(detect_psma("PSMA PET scan"))

    def test_ga68_in_description(self):
        self.assertTrue(detect_psma("GA-68 PSMA PET"))

    def test_gallium_in_description(self):
        self.assertTrue(detect_psma("Gallium-68 scan"))

    def test_psma_in_scan_type(self):
        self.assertTrue(detect_psma(None, "PSMA PET"))

    def test_no_psma(self):
        self.assertFalse(detect_psma("BRAIN MRI"))

    def test_none_values(self):
        self.assertFalse(detect_psma(None, None))


class TestComputeTotalPayment(unittest.TestCase):

    def test_uses_existing_total(self):
        """When total is already non-zero, keep it."""
        self.assertEqual(compute_total_payment(100, 50, 200), 200)

    def test_computes_from_primary_secondary(self):
        """When total is 0 but components exist, sum them."""
        self.assertEqual(compute_total_payment(100, 50, 0), 150)

    def test_computes_with_extra(self):
        self.assertEqual(compute_total_payment(100, 50, 0, 25), 175)

    def test_zero_everything(self):
        self.assertEqual(compute_total_payment(0, 0, 0), 0)

    def test_none_values(self):
        self.assertEqual(compute_total_payment(None, None, None), 0)

    def test_primary_only(self):
        self.assertEqual(compute_total_payment(500, 0, 0), 500)


class TestDeduplication(unittest.TestCase):
    """Test deduplication with database."""

    def setUp(self):
        self.app = create_app(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            TESTING=True,
        )
        self.ctx = self.app.app_context()
        self.ctx.push()

        db.session.add(BillingRecord(
            patient_name="DOE, JOHN",
            referring_doctor="DR. SMITH",
            scan_type="BRAIN MRI",
            modality="HMRI",
            insurance_carrier="M/M",
            service_date=date(2024, 1, 15),
            total_payment=750.0,
        ))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_build_dedup_set(self):
        dedup = build_dedup_set()
        self.assertIn(("DOE, JOHN", date(2024, 1, 15), "BRAIN MRI", "HMRI"), dedup)

    def test_is_duplicate_true(self):
        dedup = build_dedup_set()
        self.assertTrue(is_duplicate("DOE, JOHN", date(2024, 1, 15), "BRAIN MRI", "HMRI", dedup))

    def test_is_duplicate_false(self):
        dedup = build_dedup_set()
        self.assertFalse(is_duplicate("DOE, JANE", date(2024, 1, 15), "BRAIN MRI", "HMRI", dedup))

    def test_is_duplicate_adds_to_set(self):
        dedup = build_dedup_set()
        self.assertFalse(is_duplicate("NEW, PATIENT", date(2024, 2, 1), "CT HEAD", "CT", dedup))
        # Second call should be a duplicate now
        self.assertTrue(is_duplicate("NEW, PATIENT", date(2024, 2, 1), "CT HEAD", "CT", dedup))


class TestCSVImportCorrectness(unittest.TestCase):
    """Test that CSV import applies all normalization correctly."""

    def setUp(self):
        self.app = create_app(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            TESTING=True,
        )
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _write_csv(self, headers, rows):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for row in rows:
                writer.writerow(row)
        return path

    def test_modality_normalized(self):
        """CSV import should normalize MRI → HMRI."""
        from app.import_engine.csv_importer import import_csv
        path = self._write_csv(
            ["Patient", "Doctor", "Scan", "Modality", "Insurance", "Date", "Total"],
            [["DOE JOHN", "DR SMITH", "BRAIN", "MRI", "BCBS", "01/15/2024", "750"]]
        )
        result = import_csv(path)
        os.unlink(path)
        self.assertEqual(result["imported"], 1)
        rec = BillingRecord.query.first()
        self.assertEqual(rec.modality, "HMRI")

    def test_carrier_normalized(self):
        """CSV import should normalize MEDICARE → M/M."""
        from app.import_engine.csv_importer import import_csv
        path = self._write_csv(
            ["Patient", "Doctor", "Scan", "Modality", "Insurance", "Date", "Total"],
            [["DOE JOHN", "DR SMITH", "BRAIN", "CT", "MEDICARE", "01/15/2024", "395"]]
        )
        result = import_csv(path)
        os.unlink(path)
        self.assertEqual(result["imported"], 1)
        rec = BillingRecord.query.first()
        self.assertEqual(rec.insurance_carrier, "M/M")

    def test_total_computed_from_primary_secondary(self):
        """When total column missing, should sum primary + secondary."""
        from app.import_engine.csv_importer import import_csv
        path = self._write_csv(
            ["Patient", "Doctor", "Scan", "Modality", "Insurance", "Date", "Primary", "Secondary"],
            [["DOE JOHN", "DR SMITH", "BRAIN", "CT", "BCBS", "01/15/2024", "300", "100"]]
        )
        result = import_csv(path)
        os.unlink(path)
        self.assertEqual(result["imported"], 1)
        rec = BillingRecord.query.first()
        self.assertEqual(rec.total_payment, 400.0)

    def test_psma_detected(self):
        """CSV import should detect PSMA from description."""
        from app.import_engine.csv_importer import import_csv
        path = self._write_csv(
            ["Patient", "Doctor", "Scan", "Modality", "Insurance", "Date", "Total", "Description"],
            [["DOE JOHN", "DR SMITH", "PSMA PET", "PET", "BCBS", "01/15/2024", "3000", "GA-68 PSMA PET"]]
        )
        result = import_csv(path)
        os.unlink(path)
        self.assertEqual(result["imported"], 1)
        rec = BillingRecord.query.first()
        self.assertTrue(rec.is_psma)

    def test_dedup_prevents_duplicates(self):
        """Second import of same data should skip duplicates."""
        from app.import_engine.csv_importer import import_csv
        path = self._write_csv(
            ["Patient", "Doctor", "Scan", "Modality", "Insurance", "Date", "Total"],
            [["DOE JOHN", "DR SMITH", "BRAIN", "CT", "BCBS", "01/15/2024", "395"]]
        )
        result1 = import_csv(path)
        self.assertEqual(result1["imported"], 1)

        # Re-write and re-import same data
        path2 = self._write_csv(
            ["Patient", "Doctor", "Scan", "Modality", "Insurance", "Date", "Total"],
            [["DOE JOHN", "DR SMITH", "BRAIN", "CT", "BCBS", "01/15/2024", "395"]]
        )
        result2 = import_csv(path2)
        os.unlink(path)
        os.unlink(path2)
        self.assertEqual(result2["imported"], 0)
        self.assertEqual(result2["skipped"], 1)
        self.assertEqual(BillingRecord.query.count(), 1)

    def test_invalid_date_skipped(self):
        """Rows with unparseable dates should be skipped."""
        from app.import_engine.csv_importer import import_csv
        path = self._write_csv(
            ["Patient", "Doctor", "Scan", "Modality", "Insurance", "Date", "Total"],
            [["DOE JOHN", "DR SMITH", "BRAIN", "CT", "BCBS", "not-a-date", "395"]]
        )
        result = import_csv(path)
        os.unlink(path)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["skipped"], 1)

    def test_gado_parsed(self):
        """Gado column should be parsed correctly."""
        from app.import_engine.csv_importer import import_csv
        path = self._write_csv(
            ["Patient", "Doctor", "Scan", "Gado", "Modality", "Insurance", "Date", "Total"],
            [
                ["DOE JOHN", "DR SMITH", "BRAIN", "Y", "HMRI", "BCBS", "01/15/2024", "950"],
                ["DOE JANE", "DR SMITH", "BRAIN", "N", "HMRI", "BCBS", "01/16/2024", "750"],
            ]
        )
        result = import_csv(path)
        os.unlink(path)
        self.assertEqual(result["imported"], 2)
        recs = BillingRecord.query.order_by(BillingRecord.patient_name).all()
        self.assertTrue(recs[1].gado_used)   # DOE JOHN
        self.assertFalse(recs[0].gado_used)  # DOE JANE


class TestEraUploadCorrectness(unittest.TestCase):
    """Test that 835 ERA upload stores data correctly."""

    def setUp(self):
        self.app = create_app(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            TESTING=True,
            UPLOAD_FOLDER=tempfile.mkdtemp(),
        )
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _upload_835(self, content, filename="test.835"):
        import io
        return self.client.post(
            "/api/era/upload",
            data={"files": (io.BytesIO(content.encode()), filename)},
            content_type="multipart/form-data",
        )

    def test_duplicate_file_skipped(self):
        """Uploading the same filename twice should skip the second."""
        edi = (
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
            "SE*9*0001~GE*1*1~IEA*1*000000001~"
        )
        resp1 = self._upload_835(edi, "dedup_test.835")
        data1 = resp1.get_json()
        self.assertEqual(data1["total_payments"], 1)

        resp2 = self._upload_835(edi, "dedup_test.835")
        data2 = resp2.get_json()
        self.assertEqual(data2["total_payments"], 0)
        self.assertEqual(data2["results"][0]["status"], "skipped")

    def test_all_adjustment_codes_stored(self):
        """Multiple CAS adjustment codes should all be stored."""
        edi = (
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *240115*1200*^*00501*000000001*0*P*:~"
            "GS*HP*SENDER*RECEIVER*20240115*1200*1*X*005010X221A1~"
            "ST*835*0001~"
            "BPR*I*400.00*C*ACH*CCP*01*999999999*DA*123456789**01*888888888*DA*987654321*20240115~"
            "TRN*1*EFT88888*1234567890~"
            "N1*PR*MULTI ADJ PAYER~"
            "CLP*MULTI001*1*600.00*400.00*0.00*MA~"
            "NM1*QC*1*SMITH*JOHN****MI*111111111~"
            "DTM*232*20240201~"
            "SVC*HC:70553*600.00*400.00~"
            "CAS*CO*45*100.00~"
            "CAS*PR*1*50.00~"
            "CAS*PR*2*50.00~"
            "SE*12*0001~GE*1*1~IEA*1*000000001~"
        )
        resp = self._upload_835(edi, "multi_adj.835")
        data = resp.get_json()
        self.assertEqual(data["total_payments"], 1)

        with self.app.app_context():
            from app.models import EraClaimLine
            claim = EraClaimLine.query.first()
            self.assertIsNotNone(claim.cas_group_code)
            # Should have both CO and PR group codes
            self.assertIn("CO", claim.cas_group_code)
            self.assertIn("PR", claim.cas_group_code)
            # Should have reason codes 45, 1, 2
            self.assertIn("45", claim.cas_reason_code)
            self.assertIn("1", claim.cas_reason_code)
            # Total adjustment should be 100 + 50 + 50 = 200
            self.assertEqual(claim.cas_adjustment_amount, 200.0)

    def test_service_date_falls_back_to_payment_date(self):
        """If no DTM segment, service_date should fall back to payment date."""
        edi = (
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *240115*1200*^*00501*000000001*0*P*:~"
            "GS*HP*SENDER*RECEIVER*20240115*1200*1*X*005010X221A1~"
            "ST*835*0001~"
            "BPR*I*300.00*C*CHK*CCP*01*999999999*DA*123456789**01*888888888*DA*987654321*20240115~"
            "TRN*1*CHK77777*1234567890~"
            "N1*PR*NO DATE PAYER~"
            "CLP*NODATE001*1*300.00*300.00*0.00*MA~"
            "NM1*QC*1*JONES*BOB****MI*222222222~"
            "SVC*HC:99213*300.00*300.00~"
            "SE*8*0001~GE*1*1~IEA*1*000000001~"
        )
        resp = self._upload_835(edi, "no_date.835")
        data = resp.get_json()
        self.assertEqual(data["total_payments"], 1)

        with self.app.app_context():
            from app.models import EraClaimLine
            claim = EraClaimLine.query.first()
            # Should fall back to payment date 2024-01-15
            self.assertIsNotNone(claim.service_date_835)
            self.assertEqual(claim.service_date_835, date(2024, 1, 15))


class TestValidateBillingRecord(unittest.TestCase):

    def test_valid_record(self):
        is_valid, errors = validate_billing_record(
            "DOE JOHN", date(2024, 1, 15), "DR SMITH", "BRAIN", "HMRI", "BCBS"
        )
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])

    def test_missing_name(self):
        is_valid, errors = validate_billing_record(
            "", date(2024, 1, 15)
        )
        self.assertFalse(is_valid)
        self.assertIn("Missing patient name", errors)

    def test_missing_date(self):
        is_valid, errors = validate_billing_record(
            "DOE JOHN", None
        )
        self.assertFalse(is_valid)
        self.assertIn("Missing or invalid service date", errors)


if __name__ == "__main__":
    unittest.main()
