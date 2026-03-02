"""Tests for filing deadline tracker API (F-06)."""

from datetime import date, timedelta
from decimal import Decimal

from app.models import BillingRecord
from app.extensions import db


def _insert_deadline_records(app):
    """Insert records with various filing deadline scenarios."""
    today = date.today()

    with app.app_context():
        # Past deadline: deadline was 30 days ago
        past = BillingRecord(
            patient_name='PAST, DEADLINE',
            referring_doctor='DR A',
            scan_type='BRAIN',
            modality='HMRI',
            insurance_carrier='M/M',
            service_date=today - timedelta(days=400),
            total_payment=Decimal('0'),
            primary_payment=Decimal('0'),
            secondary_payment=Decimal('0'),
            appeal_deadline=today - timedelta(days=30),
            import_source='EXCEL_IMPORT',
        )

        # Warning: deadline is 15 days from now
        warning = BillingRecord(
            patient_name='WARNING, SOON',
            referring_doctor='DR B',
            scan_type='CHEST',
            modality='CT',
            insurance_carrier='INS',
            service_date=today - timedelta(days=165),
            total_payment=Decimal('0'),
            primary_payment=Decimal('0'),
            secondary_payment=Decimal('0'),
            appeal_deadline=today + timedelta(days=15),
            import_source='EXCEL_IMPORT',
        )

        # Safe: deadline is 90 days from now
        safe = BillingRecord(
            patient_name='SAFE, RECORD',
            referring_doctor='DR C',
            scan_type='PELVIS',
            modality='CT',
            insurance_carrier='INS',
            service_date=today - timedelta(days=90),
            total_payment=Decimal('0'),
            primary_payment=Decimal('0'),
            secondary_payment=Decimal('0'),
            appeal_deadline=today + timedelta(days=90),
            import_source='EXCEL_IMPORT',
        )

        # Paid record (should NOT appear in filing deadlines)
        paid = BillingRecord(
            patient_name='PAID, ALREADY',
            referring_doctor='DR D',
            scan_type='BRAIN',
            modality='HMRI',
            insurance_carrier='M/M',
            service_date=today - timedelta(days=100),
            total_payment=Decimal('750.00'),
            primary_payment=Decimal('750.00'),
            secondary_payment=Decimal('0'),
            appeal_deadline=today + timedelta(days=265),
            import_source='EXCEL_IMPORT',
        )

        db.session.add_all([past, warning, safe, paid])
        db.session.commit()


def test_list_filing_deadlines(client, app):
    """GET /api/filing-deadlines returns unpaid records with status."""
    _insert_deadline_records(app)
    resp = client.get('/api/filing-deadlines')
    assert resp.status_code == 200
    data = resp.get_json()
    # Should include 3 unpaid records (past, warning, safe) but not the paid one
    assert data['total'] == 3
    statuses = {item['filing_status'] for item in data['items']}
    assert 'PAST_DEADLINE' in statuses
    assert 'WARNING_30DAY' in statuses
    assert 'SAFE' in statuses


def test_filing_deadlines_status_filter(client, app):
    """GET /api/filing-deadlines?status=PAST_DEADLINE filters."""
    _insert_deadline_records(app)
    resp = client.get('/api/filing-deadlines?status=PAST_DEADLINE')
    data = resp.get_json()
    for item in data['items']:
        assert item['filing_status'] == 'PAST_DEADLINE'


def test_filing_alerts(client, app):
    """GET /api/filing-deadlines/alerts returns counts."""
    _insert_deadline_records(app)
    resp = client.get('/api/filing-deadlines/alerts')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['past_deadline'] == 1
    assert data['warning_30day'] == 1
    assert data['total_alerts'] == 2
    assert len(data['past_deadline_details']) == 1
    assert len(data['warning_details']) == 1


def test_filing_alerts_empty(client, app):
    """GET /api/filing-deadlines/alerts with no data returns zeros."""
    resp = client.get('/api/filing-deadlines/alerts')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['past_deadline'] == 0
    assert data['warning_30day'] == 0
