"""Tests for underpayment detection API (F-05)."""

from datetime import date
from decimal import Decimal

from app.models import BillingRecord
from app.extensions import db


def _insert_test_records(app):
    """Insert test billing records with known underpayment scenarios."""
    with app.app_context():
        # Underpaid: HMRI pays $500 vs expected $750 (66.7%)
        underpaid = BillingRecord(
            patient_name='UNDER, PAID',
            referring_doctor='DR A',
            scan_type='BRAIN',
            modality='HMRI',
            insurance_carrier='M/M',
            service_date=date(2025, 6, 1),
            total_payment=Decimal('500.00'),
            primary_payment=Decimal('500.00'),
            secondary_payment=Decimal('0'),
            expected_rate=Decimal('750.00'),
            variance=Decimal('-250.00'),
            pct_of_expected=Decimal('0.6667'),
            import_source='EXCEL_IMPORT',
        )

        # Properly paid: CT pays $395 vs expected $395 (100%)
        proper = BillingRecord(
            patient_name='PROPER, PAY',
            referring_doctor='DR B',
            scan_type='CHEST',
            modality='CT',
            insurance_carrier='INS',
            service_date=date(2025, 6, 2),
            total_payment=Decimal('395.00'),
            primary_payment=Decimal('395.00'),
            secondary_payment=Decimal('0'),
            expected_rate=Decimal('395.00'),
            variance=Decimal('0.00'),
            pct_of_expected=Decimal('1.0000'),
            import_source='EXCEL_IMPORT',
        )

        # Unpaid (should not appear in underpayments)
        unpaid = BillingRecord(
            patient_name='UN, PAID',
            referring_doctor='DR C',
            scan_type='PELVIS',
            modality='CT',
            insurance_carrier='INS',
            service_date=date(2025, 6, 3),
            total_payment=Decimal('0'),
            primary_payment=Decimal('0'),
            secondary_payment=Decimal('0'),
            expected_rate=Decimal('395.00'),
            import_source='EXCEL_IMPORT',
        )

        db.session.add_all([underpaid, proper, unpaid])
        db.session.commit()


def test_list_underpayments(client, app):
    """GET /api/underpayments returns only underpaid records."""
    _insert_test_records(app)
    resp = client.get('/api/underpayments')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['total'] == 1
    assert data['items'][0]['patient_name'] == 'UNDER, PAID'
    assert data['items'][0]['variance'] < 0


def test_underpayments_carrier_filter(client, app):
    """GET /api/underpayments?carrier= filters correctly."""
    _insert_test_records(app)
    resp = client.get('/api/underpayments?carrier=M/M')
    data = resp.get_json()
    assert data['total'] == 1

    resp2 = client.get('/api/underpayments?carrier=NONEXISTENT')
    data2 = resp2.get_json()
    assert data2['total'] == 0


def test_underpayments_modality_filter(client, app):
    """GET /api/underpayments?modality= filters correctly."""
    _insert_test_records(app)
    resp = client.get('/api/underpayments?modality=HMRI')
    data = resp.get_json()
    assert data['total'] == 1


def test_underpayments_summary(client, app):
    """GET /api/underpayments/summary returns aggregate stats."""
    _insert_test_records(app)
    resp = client.get('/api/underpayments/summary')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['total_flagged'] == 1
    assert data['total_variance'] < 0
    assert len(data['by_carrier']) >= 1
    assert len(data['by_modality']) >= 1


def test_underpayments_empty(client, app):
    """GET /api/underpayments with no data returns empty list."""
    resp = client.get('/api/underpayments')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['total'] == 0
    assert data['items'] == []
