"""Tests for Excel import API (F-01)."""

import io
import os
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app.models import BillingRecord


def test_import_no_file(client):
    """POST without file returns 400."""
    resp = client.post('/api/import/excel')
    assert resp.status_code == 400
    assert 'No file provided' in resp.get_json()['error']


def test_import_invalid_extension(client):
    """POST with non-Excel file returns 400."""
    data = {'file': (io.BytesIO(b'not excel'), 'test.txt')}
    resp = client.post('/api/import/excel', data=data, content_type='multipart/form-data')
    assert resp.status_code == 400
    assert 'Invalid file type' in resp.get_json()['error']


def test_import_excel_success(client, app):
    """POST with valid Excel file imports records."""
    mock_records = [
        {
            'patient_name': 'DOE, JOHN',
            'patient_name_display': 'DOE, JOHN',
            'patient_id': 12345,
            'birth_date': date(1960, 1, 15),
            'service_date': date(2025, 6, 1),
            'schedule_date': None,
            'scan_type': 'BRAIN',
            'modality': 'HMRI',
            'gado_used': True,
            'is_new_patient': False,
            'referring_doctor': 'SMITH, DR',
            'insurance_carrier': 'M/M',
            'reading_physician': 'JONES, DR',
            'primary_payment': Decimal('750.00'),
            'secondary_payment': Decimal('0'),
            'total_payment': Decimal('750.00'),
            'extra_charges': Decimal('0'),
            'service_month': 'Jun',
            'service_year': '2025',
            'is_research': False,
            'is_psma': False,
            'source': 'OCMRI',
            'notes': '',
            'source_row': 2,
            'review_flags': [],
        },
        {
            'patient_name': 'SMITH, JANE',
            'patient_name_display': 'SMITH, JANE',
            'patient_id': 12346,
            'birth_date': date(1975, 5, 20),
            'service_date': date(2025, 6, 2),
            'schedule_date': None,
            'scan_type': 'CHEST',
            'modality': 'CT',
            'gado_used': False,
            'is_new_patient': True,
            'referring_doctor': 'BROWN, DR',
            'insurance_carrier': 'INS',
            'reading_physician': 'JONES, DR',
            'primary_payment': Decimal('200.00'),
            'secondary_payment': Decimal('0'),
            'total_payment': Decimal('200.00'),
            'extra_charges': Decimal('0'),
            'service_month': 'Jun',
            'service_year': '2025',
            'is_research': False,
            'is_psma': False,
            'source': 'OCMRI',
            'notes': '',
            'source_row': 3,
            'review_flags': [],
        },
    ]

    with patch('app.import_engine.routes.read_ocmri', return_value=mock_records):
        data = {'file': (io.BytesIO(b'fake xlsx content'), 'OCMRI.xlsx')}
        resp = client.post('/api/import/excel', data=data, content_type='multipart/form-data')

    assert resp.status_code == 200
    result = resp.get_json()
    assert result['imported'] == 2
    assert result['skipped'] == 0
    assert result['total_in_file'] == 2
    assert 'duration_ms' in result

    # Verify records in DB
    with app.app_context():
        records = BillingRecord.query.all()
        assert len(records) == 2
        doe = BillingRecord.query.filter_by(patient_name='DOE, JOHN').first()
        assert doe is not None
        assert doe.modality == 'HMRI'
        assert doe.gado_used is True
        assert doe.appeal_deadline is not None
        assert doe.import_source == 'EXCEL_IMPORT'
        assert doe.expected_rate is not None


def test_import_dedup(client, app):
    """Second import of same records should skip duplicates."""
    mock_records = [{
        'patient_name': 'DOE, JOHN',
        'patient_name_display': 'DOE, JOHN',
        'patient_id': None,
        'birth_date': None,
        'service_date': date(2025, 6, 1),
        'schedule_date': None,
        'scan_type': 'BRAIN',
        'modality': 'HMRI',
        'gado_used': False,
        'is_new_patient': False,
        'referring_doctor': '',
        'insurance_carrier': 'M/M',
        'reading_physician': None,
        'primary_payment': Decimal('0'),
        'secondary_payment': Decimal('0'),
        'total_payment': Decimal('0'),
        'extra_charges': Decimal('0'),
        'service_month': '',
        'service_year': '',
        'is_research': False,
        'is_psma': False,
        'source': '',
        'notes': '',
        'source_row': 2,
        'review_flags': [],
    }]

    with patch('app.import_engine.routes.read_ocmri', return_value=mock_records):
        data = {'file': (io.BytesIO(b'fake'), 'OCMRI.xlsx')}
        resp1 = client.post('/api/import/excel', data=data, content_type='multipart/form-data')
        assert resp1.get_json()['imported'] == 1

        data2 = {'file': (io.BytesIO(b'fake'), 'OCMRI.xlsx')}
        resp2 = client.post('/api/import/excel', data=data2, content_type='multipart/form-data')
        assert resp2.get_json()['imported'] == 0
        assert resp2.get_json()['skipped'] == 1


def test_import_status(client, app):
    """GET /api/import/status returns statistics."""
    resp = client.get('/api/import/status')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'total_records' in data
    assert 'by_source' in data
    assert 'has_data' in data
    assert data['has_data'] is False  # No imports yet
