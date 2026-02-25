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
            era_payment = store_parsed_835(parsed)
            assert era_payment.id is not None
            assert era_payment.filename == 'test.835'
            assert era_payment.payment_amount == 1500.00
            assert era_payment.check_eft_number == 'EFT12345'

    def test_store_creates_claim_lines(self, app):
        from app.parser.era_835_parser import store_parsed_835
        with app.app_context():
            parsed = parse_835_content(SAMPLE_835, 'test.835')
            era_payment = store_parsed_835(parsed)
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
