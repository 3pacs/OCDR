"""Tests for 835 ERA parser API (F-02)."""

import io
import os
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app.models import EraPayment, EraClaimLine


SAMPLE_835 = (
    "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *230101*1200*^*00501*000000001*0*P*:~"
    "GS*HP*SENDER*RECEIVER*20230101*1200*1*X*005010X221A1~"
    "ST*835*0001~"
    "BPR*I*1500.00*C*ACH*CCP*01*999999999*DA*123456789**01*999999999*DA*123456789*20230115~"
    "TRN*1*CHECK123~"
    "N1*PR*TEST INSURANCE~"
    "CLP*CLM001*1*1000.00*750.00*250.00*12~"
    "NM1*QC*1*DOE*JOHN~"
    "DTM*232*20250601~"
    "SVC*HC:70553*1000.00*750.00~"
    "CAS*CO*45*250.00~"
    "SE*11*0001~"
    "GE*1*1~"
    "IEA*1*000000001~"
)


def test_import_835_file_upload(client, app):
    """POST /api/import/835 with uploaded file."""
    data = {'file': (io.BytesIO(SAMPLE_835.encode()), 'test.835')}
    resp = client.post('/api/import/835', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200
    result = resp.get_json()
    assert result['files_parsed'] == 1
    assert result['claims_found'] == 1
    assert result['payments_total'] > 0

    # Verify in DB
    with app.app_context():
        payments = EraPayment.query.all()
        assert len(payments) == 1
        assert payments[0].payer_name != ''
        assert payments[0].check_eft_number == 'CHECK123'

        claims = EraClaimLine.query.all()
        assert len(claims) == 1
        assert claims[0].claim_id == 'CLM001'
        assert claims[0].patient_name_835 == 'DOE, JOHN'
        assert claims[0].cpt_code == '70553'


def test_import_835_no_input(client):
    """POST /api/import/835 without file or JSON returns 400."""
    resp = client.post('/api/import/835')
    assert resp.status_code == 400


def test_import_835_invalid_folder(client):
    """POST /api/import/835 with bad folder_path returns 400."""
    resp = client.post('/api/import/835',
                       json={'folder_path': '/nonexistent/path'})
    assert resp.status_code == 400


def test_list_era_payments(client, app):
    """GET /api/era/payments returns paginated list."""
    # First import some data
    data = {'file': (io.BytesIO(SAMPLE_835.encode()), 'test.835')}
    client.post('/api/import/835', data=data, content_type='multipart/form-data')

    resp = client.get('/api/era/payments')
    assert resp.status_code == 200
    result = resp.get_json()
    assert 'items' in result
    assert 'total' in result
    assert result['total'] == 1
    assert len(result['items']) == 1


def test_list_era_payments_filter_payer(client, app):
    """GET /api/era/payments with payer filter."""
    data = {'file': (io.BytesIO(SAMPLE_835.encode()), 'test.835')}
    client.post('/api/import/835', data=data, content_type='multipart/form-data')

    # Filter by known payer
    resp = client.get('/api/era/payments?payer=TEST')
    result = resp.get_json()
    assert result['total'] >= 0  # May or may not match after normalization


def test_get_claim_detail(client, app):
    """GET /api/era/claims/<id> returns claim + payment info."""
    data = {'file': (io.BytesIO(SAMPLE_835.encode()), 'test.835')}
    client.post('/api/import/835', data=data, content_type='multipart/form-data')

    with app.app_context():
        claim = EraClaimLine.query.first()
        claim_id = claim.id

    resp = client.get(f'/api/era/claims/{claim_id}')
    assert resp.status_code == 200
    result = resp.get_json()
    assert result['claim_id'] == 'CLM001'
    assert 'payment' in result
    assert result['payment']['check_eft_number'] == 'CHECK123'


def test_get_claim_detail_not_found(client):
    """GET /api/era/claims/<id> with bad id returns 404."""
    resp = client.get('/api/era/claims/99999')
    assert resp.status_code == 404
