"""Tests for app factory and /health endpoint (F-00)."""

from app.models import Payer, FeeSchedule


def test_health_endpoint(client):
    resp = client.get('/health')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'healthy'
    assert 'record_count' in data
    assert 'uptime_seconds' in data


def test_seed_data_populated(app):
    """Verify payer and fee schedule seed data is present."""
    with app.app_context():
        payers = Payer.query.all()
        assert len(payers) > 0

        # Check a known payer exists
        mm = Payer.query.get('M/M')
        assert mm is not None
        assert mm.display_name == 'Medicare/Medicaid'
        assert mm.filing_deadline_days == 365
        assert mm.expected_has_secondary is True

        # Check fee schedule
        schedules = FeeSchedule.query.all()
        assert len(schedules) > 0

        ct = FeeSchedule.query.filter_by(payer_code='DEFAULT', modality='CT').first()
        assert ct is not None
        assert float(ct.expected_rate) == 395.0


def test_health_returns_db_size(client):
    resp = client.get('/health')
    data = resp.get_json()
    # In-memory SQLite won't have a file, so db_size_bytes should be 0
    assert 'db_size_bytes' in data
