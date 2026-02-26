"""Tests for the X12 835 ERA parser (F-02)."""
import os
import sys
import pytest
import tempfile

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.models import db, EraPayment, EraClaimLine
from app.parser.era_835_parser import parse_835_content, parse_date, parse_amount


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-secret'


# Sample 835 content with realistic structure
SAMPLE_835 = (
    "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
    "*210101*1200*^*00501*000000001*0*P*:~"
    "GS*HP*SENDER*RECEIVER*20210101*1200*1*X*005010X221A1~"
    "ST*835*0001~"
    "BPR*I*1500.00*C*ACH*CCP*01*999999999*DA*1234567890**01*999888777*DA"
    "*9876543210*20210115**~"
    "TRN*1*EFT12345*1234567890~"
    "N1*PR*BLUE CROSS BLUE SHIELD~"
    "N1*PE*ORANGE COUNTY DIAGNOSTIC*XX*1234567890~"
    "CLP*CLM001*1*500.00*450.00*50.00*12*12345678901234*11~"
    "NM1*QC*1*SMITH*JOHN****MI*12345~"
    "DTM*232*20210101~"
    "SVC*HC:74177*500.00*450.00~"
    "CAS*CO*45*50.00~"
    "CLP*CLM002*4*800.00*0.00*0.00*12*98765432109876*11~"
    "NM1*QC*1*DOE*JANE****MI*67890~"
    "DTM*232*20210105~"
    "SVC*HC:78816*800.00*0.00~"
    "CAS*CO*4*800.00~"
    "CLP*CLM003*1*250.00*200.00*50.00*12*11111111111111*11~"
    "NM1*QC*1*JONES*MARY****MI*11111~"
    "DTM*232*20210110~"
    "SVC*HC:70553*250.00*200.00~"
    "CAS*PR*1*30.00*2*20.00~"
    "SE*25*0001~"
    "GE*1*1~"
    "IEA*1*000000001~"
)


class TestParseDateAmount:
    """Test helper functions."""

    def test_parse_date_valid(self):
        d = parse_date('20210115')
        assert d is not None
        assert d.year == 2021
        assert d.month == 1
        assert d.day == 15

    def test_parse_date_none(self):
        assert parse_date(None) is None

    def test_parse_date_short(self):
        assert parse_date('2021') is None

    def test_parse_date_invalid(self):
        assert parse_date('NOTADATE') is None

    def test_parse_amount_valid(self):
        assert parse_amount('1500.00') == 1500.00

    def test_parse_amount_negative(self):
        assert parse_amount('-250.50') == -250.50

    def test_parse_amount_none(self):
        assert parse_amount(None) == 0.0

    def test_parse_amount_invalid(self):
        assert parse_amount('ABC') == 0.0


class TestParse835Content:
    """Test the core 835 parser logic."""

    def test_payment_info(self):
        result = parse_835_content(SAMPLE_835, 'test.835')
        payment = result['payment']
        assert payment['filename'] == 'test.835'
        assert payment['payment_method'] == 'I'
        assert payment['payment_amount'] == 1500.00
        assert payment['check_eft_number'] == 'EFT12345'
        assert payment['payer_name'] == 'BLUE CROSS BLUE SHIELD'
        assert payment['payment_date'] is not None
        assert payment['payment_date'].year == 2021
        assert payment['payment_date'].month == 1
        assert payment['payment_date'].day == 15

    def test_claim_count(self):
        result = parse_835_content(SAMPLE_835, 'test.835')
        assert len(result['claims']) == 3

    def test_first_claim(self):
        result = parse_835_content(SAMPLE_835, 'test.835')
        claim = result['claims'][0]
        assert claim['claim_id'] == 'CLM001'
        assert claim['claim_status'] == '1'  # processed primary
        assert claim['billed_amount'] == 500.00
        assert claim['paid_amount'] == 450.00
        assert claim['patient_name_835'] == 'SMITH, JOHN'
        assert claim['cpt_code'] == '74177'
        assert claim['cas_group_code'] == 'CO'
        assert claim['cas_reason_code'] == '45'
        assert claim['cas_adjustment_amount'] == 50.00

    def test_denied_claim(self):
        result = parse_835_content(SAMPLE_835, 'test.835')
        claim = result['claims'][1]
        assert claim['claim_id'] == 'CLM002'
        assert claim['claim_status'] == '4'  # denied
        assert claim['paid_amount'] == 0.00
        assert claim['patient_name_835'] == 'DOE, JANE'
        assert claim['cas_group_code'] == 'CO'
        assert claim['cas_reason_code'] == '4'  # not covered

    def test_third_claim_with_patient_responsibility(self):
        result = parse_835_content(SAMPLE_835, 'test.835')
        claim = result['claims'][2]
        assert claim['claim_id'] == 'CLM003'
        assert claim['patient_name_835'] == 'JONES, MARY'
        assert claim['paid_amount'] == 200.00
        assert claim['cas_group_code'] == 'PR'
        assert claim['cas_reason_code'] == '1'  # deductible

    def test_service_dates(self):
        result = parse_835_content(SAMPLE_835, 'test.835')
        for claim in result['claims']:
            assert claim['service_date_835'] is not None
            assert claim['service_date_835'].year == 2021

    def test_empty_content(self):
        result = parse_835_content('', 'empty.835')
        assert result['claims'] == []
        assert result['payment']['payment_amount'] == 0.0


class TestStore835:
    """Test storing parsed 835 data into the database."""

    @pytest.fixture
    def app(self):
        app = create_app(TestConfig)
        with app.app_context():
            db.create_all()
            yield app
            db.session.remove()
            db.drop_all()

    def test_store_creates_era_payment(self, app):
        from app.parser.era_835_parser import store_parsed_835
        with app.app_context():
            parsed = parse_835_content(SAMPLE_835, 'test.835')
            era_payment, claims_new, claims_dup = store_parsed_835(parsed)
            assert era_payment.id is not None
            assert era_payment.filename == 'test.835'
            assert era_payment.payment_amount == 1500.00
            assert era_payment.check_eft_number == 'EFT12345'

    def test_store_creates_claim_lines(self, app):
        from app.parser.era_835_parser import store_parsed_835
        with app.app_context():
            parsed = parse_835_content(SAMPLE_835, 'test.835')
            era_payment, claims_new, claims_dup = store_parsed_835(parsed)
            claims = EraClaimLine.query.filter_by(era_payment_id=era_payment.id).all()
            assert len(claims) == 3

    def test_store_claim_line_details(self, app):
        from app.parser.era_835_parser import store_parsed_835
        with app.app_context():
            parsed = parse_835_content(SAMPLE_835, 'test.835')
            store_parsed_835(parsed)
            claim = EraClaimLine.query.filter_by(claim_id='CLM001').first()
            assert claim is not None
            assert claim.patient_name_835 == 'SMITH, JOHN'
            assert claim.paid_amount == 450.00


class TestAPI835:
    """Test 835 API endpoints."""

    @pytest.fixture
    def client(self):
        app = create_app(TestConfig)
        with app.app_context():
            db.create_all()
            yield app.test_client()
            db.session.remove()
            db.drop_all()

    def test_import_835_file_upload(self, client):
        import io
        data = {'file': (io.BytesIO(SAMPLE_835.encode()), 'test.835')}
        response = client.post('/api/import/835', data=data, content_type='multipart/form-data')
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['files_parsed'] == 1
        assert json_data['claims_found'] == 3
        assert json_data['payments_total'] == 1500.00

    def test_list_era_payments(self, client):
        # First import a file
        import io
        data = {'file': (io.BytesIO(SAMPLE_835.encode()), 'test.835')}
        client.post('/api/import/835', data=data, content_type='multipart/form-data')

        response = client.get('/api/era/payments')
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['total'] == 1

    def test_get_era_claim(self, client):
        import io
        data = {'file': (io.BytesIO(SAMPLE_835.encode()), 'test.835')}
        client.post('/api/import/835', data=data, content_type='multipart/form-data')

        response = client.get('/api/era/claims/1')
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['claim_id'] == 'CLM001'

    def test_import_835_no_file(self, client):
        response = client.post('/api/import/835')
        assert response.status_code == 400


class TestEobDirectoryScan:
    """Test EOB directory scanning with recursive traversal and dedup."""

    @pytest.fixture
    def app(self):
        app = create_app(TestConfig)
        with app.app_context():
            db.create_all()
            yield app
            db.session.remove()
            db.drop_all()

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    def _write_file(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)

    def test_recursive_scan_finds_subfolders(self, client):
        """Files in nested subfolders should be found and imported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_file(os.path.join(tmpdir, 'root.835'), SAMPLE_835)
            # Exact same content = content duplicate
            self._write_file(os.path.join(tmpdir, 'sub1', 'copy.835'), SAMPLE_835)
            # Different content
            alt_835 = SAMPLE_835.replace('EFT12345', 'EFT99999').replace('CLM001', 'CLM801')
            self._write_file(os.path.join(tmpdir, 'sub1', 'sub2', 'deep.edi'), alt_835)

            resp = client.post('/api/import/eob-scan', json={'folder_path': tmpdir})
            data = resp.get_json()

            assert resp.status_code == 200
            assert data['total_files_found'] == 3
            # root.835 imported, copy.835 is byte-identical = dup, deep.edi is different = imported
            assert data['files_imported'] == 2
            assert data['skip_reasons']['duplicate_content'] == 1

    def test_duplicate_content_skipped(self, client):
        """Byte-identical files in different folders should be deduplicated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_file(os.path.join(tmpdir, 'a', 'file1.835'), SAMPLE_835)
            self._write_file(os.path.join(tmpdir, 'b', 'file2.835'), SAMPLE_835)
            self._write_file(os.path.join(tmpdir, 'c', 'file3.835'), SAMPLE_835)

            resp = client.post('/api/import/eob-scan', json={'folder_path': tmpdir})
            data = resp.get_json()

            assert data['files_imported'] == 1
            assert data['skip_reasons']['duplicate_content'] == 2

    def test_already_imported_skipped(self, client):
        """Files with filenames matching previously imported ERA payments are skipped."""
        import io
        # Pre-import a file via the standard upload
        upload_data = {'file': (io.BytesIO(SAMPLE_835.encode()), 'existing.835')}
        client.post('/api/import/835', data=upload_data, content_type='multipart/form-data')

        with tempfile.TemporaryDirectory() as tmpdir:
            # Same filename as what's already in the DB
            self._write_file(os.path.join(tmpdir, 'existing.835'), SAMPLE_835)

            resp = client.post('/api/import/eob-scan', json={'folder_path': tmpdir})
            data = resp.get_json()

            assert data['files_imported'] == 0
            assert data['skip_reasons']['already_imported'] == 1

    def test_txt_files_validated_as_835(self, client):
        """Text files that don't contain 835 content should be skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_file(os.path.join(tmpdir, 'valid.txt'), SAMPLE_835)
            self._write_file(os.path.join(tmpdir, 'readme.txt'), 'This is just a readme file.')
            self._write_file(os.path.join(tmpdir, 'notes.txt'), 'Patient notes from 2024.')

            resp = client.post('/api/import/eob-scan', json={'folder_path': tmpdir})
            data = resp.get_json()

            assert data['files_imported'] == 1
            assert data['skip_reasons']['not_835_content'] == 2

    def test_eob_scan_missing_folder(self, client):
        """Nonexistent folder returns 400."""
        resp = client.post('/api/import/eob-scan', json={'folder_path': '/no/such/path'})
        assert resp.status_code == 400
        assert 'error' in resp.get_json()

    def test_eob_scan_no_body(self, client):
        """Missing JSON body returns 400."""
        resp = client.post('/api/import/eob-scan')
        assert resp.status_code == 400

    def test_is_835_content_heuristic(self):
        """Test the is_835_content helper directly."""
        from app.parser.era_835_parser import is_835_content
        assert is_835_content(SAMPLE_835) is True
        assert is_835_content('ISA*00*stuff') is True
        assert is_835_content('Just a text file with notes') is False
        assert is_835_content('') is False


class TestClaimLevelDedup:
    """Test claim-level deduplication across files (e.g. .835 vs .txt same claims)."""

    @pytest.fixture
    def app(self):
        app = create_app(TestConfig)
        with app.app_context():
            db.create_all()
            yield app
            db.session.remove()
            db.drop_all()

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    def _write_file(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)

    def test_store_returns_new_and_dup_counts(self, app):
        """store_parsed_835 returns (era_payment, claims_new, claims_duplicate)."""
        from app.parser.era_835_parser import store_parsed_835
        with app.app_context():
            parsed = parse_835_content(SAMPLE_835, 'first.835')
            era_payment, claims_new, claims_dup = store_parsed_835(parsed)
            assert era_payment is not None
            assert claims_new == 3
            assert claims_dup == 0

    def test_duplicate_claims_detected_on_reimport(self, app):
        """Importing the same claims a second time flags them as duplicates."""
        from app.parser.era_835_parser import store_parsed_835
        with app.app_context():
            parsed = parse_835_content(SAMPLE_835, 'first.835')
            store_parsed_835(parsed)

            # Import again with a different filename but same claim data
            parsed2 = parse_835_content(SAMPLE_835, 'second.txt')
            era_payment2, claims_new, claims_dup = store_parsed_835(parsed2)
            # All 3 claims are duplicates; payment header should be removed
            assert era_payment2 is None
            assert claims_new == 0
            assert claims_dup == 3

    def test_partial_duplicate_keeps_new_claims(self, app):
        """File with mix of new and duplicate claims: new ones are stored, dups skipped."""
        from app.parser.era_835_parser import store_parsed_835
        with app.app_context():
            parsed = parse_835_content(SAMPLE_835, 'first.835')
            store_parsed_835(parsed)

            # Build a variant with 2 existing claims + 1 new claim
            variant = SAMPLE_835.replace('CLM003', 'CLM999')
            parsed2 = parse_835_content(variant, 'partial.txt')
            era_payment2, claims_new, claims_dup = store_parsed_835(parsed2)
            assert era_payment2 is not None
            assert claims_new == 1  # CLM999 is new
            assert claims_dup == 2  # CLM001 and CLM002 already existed

    def test_txt_duplicate_claims_skipped_in_folder_scan(self, client):
        """Folder scan: a .txt file with all-duplicate claims is skipped."""
        import io
        # First import the claims via direct upload
        upload_data = {'file': (io.BytesIO(SAMPLE_835.encode()), 'original.835')}
        client.post('/api/import/835', data=upload_data, content_type='multipart/form-data')

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write same claims as a .txt file (different filename, same claim content)
            txt_path = os.path.join(tmpdir, 'vendor_copy.txt')
            os.makedirs(os.path.dirname(txt_path), exist_ok=True)
            with open(txt_path, 'w') as f:
                f.write(SAMPLE_835)

            resp = client.post('/api/import/eob-scan', json={'folder_path': tmpdir})
            data = resp.get_json()

            assert resp.status_code == 200
            assert data['files_imported'] == 0
            assert data['skip_reasons']['duplicate_claims'] == 1
            assert data['claims_duplicate'] >= 3

    def test_upload_reports_claim_dedup_counts(self, client):
        """Single file upload API now reports claims_new and claims_duplicate."""
        import io
        # First upload
        data1 = {'file': (io.BytesIO(SAMPLE_835.encode()), 'first.835')}
        resp1 = client.post('/api/import/835', data=data1, content_type='multipart/form-data')
        json1 = resp1.get_json()
        assert json1['claims_new'] == 3
        assert json1['claims_duplicate'] == 0

        # Second upload of same claims with different filename
        data2 = {'file': (io.BytesIO(SAMPLE_835.encode()), 'second.txt')}
        resp2 = client.post('/api/import/835', data=data2, content_type='multipart/form-data')
        json2 = resp2.get_json()
        assert json2['claims_new'] == 0
        assert json2['claims_duplicate'] == 3

    def test_different_paid_amount_is_not_duplicate(self, app):
        """Same claim_id but different paid_amount should be treated as unique."""
        from app.parser.era_835_parser import store_parsed_835
        with app.app_context():
            parsed = parse_835_content(SAMPLE_835, 'first.835')
            store_parsed_835(parsed)

            # Change the paid amount for CLM001 (simulates a corrected payment)
            variant = SAMPLE_835.replace(
                'CLP*CLM001*1*500.00*450.00',
                'CLP*CLM001*1*500.00*475.00'
            )
            parsed2 = parse_835_content(variant, 'corrected.txt')
            era_payment2, claims_new, claims_dup = store_parsed_835(parsed2)
            # CLM001 with different paid_amount is new; CLM002 and CLM003 are dups
            assert claims_new == 1
            assert claims_dup == 2

    def test_no_claims_in_db_after_full_dedup(self, app):
        """When all claims are duplicates, no orphan EraPayment remains in DB."""
        from app.parser.era_835_parser import store_parsed_835
        with app.app_context():
            parsed = parse_835_content(SAMPLE_835, 'first.835')
            store_parsed_835(parsed)

            parsed2 = parse_835_content(SAMPLE_835, 'duplicate.txt')
            era_payment2, _, _ = store_parsed_835(parsed2)
            assert era_payment2 is None

            # Only 1 EraPayment should exist (the first one)
            assert EraPayment.query.count() == 1
            # Only 3 claim lines (no duplicates stored)
            assert EraClaimLine.query.count() == 3


class TestAPIHealth:
    """Test health endpoint (F-00)."""

    @pytest.fixture
    def client(self):
        app = create_app(TestConfig)
        with app.app_context():
            db.create_all()
            yield app.test_client()
            db.session.remove()
            db.drop_all()

    def test_health(self, client):
        response = client.get('/health')
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['status'] == 'ok'
        assert 'record_count' in json_data
        assert 'uptime_seconds' in json_data
