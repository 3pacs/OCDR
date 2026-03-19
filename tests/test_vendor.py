"""Tests for vendor credential store and API routes."""
import os
import tempfile
import pytest

from app import create_app
from app.models import db
from app.vendor.credential_store import CredentialStore


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-secret'


class TestCredentialStore:
    """Test encrypted credential storage."""

    def test_create_new_store(self):
        with tempfile.NamedTemporaryFile(suffix='.enc', delete=False) as f:
            path = f.name
        os.unlink(path)  # start fresh

        try:
            store = CredentialStore(path)
            store.unlock('my-master-password')
            store.set('officeally', 'user1', 'pass1')
            store.save()

            # Verify file was created and is not empty
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_store_and_retrieve(self):
        with tempfile.NamedTemporaryFile(suffix='.enc', delete=False) as f:
            path = f.name
        os.unlink(path)

        try:
            # Store credentials
            store = CredentialStore(path)
            store.unlock('master123')
            store.set('officeally', 'testuser', 'testpass')
            store.set('purview', 'pvuser', 'pvpass')
            store.save()

            # Reload and verify
            store2 = CredentialStore(path)
            store2.unlock('master123')
            creds = store2.get('officeally')
            assert creds is not None
            assert creds['username'] == 'testuser'
            assert creds['password'] == 'testpass'

            creds2 = store2.get('purview')
            assert creds2['username'] == 'pvuser'
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_wrong_password_fails(self):
        with tempfile.NamedTemporaryFile(suffix='.enc', delete=False) as f:
            path = f.name
        os.unlink(path)

        try:
            store = CredentialStore(path)
            store.unlock('correct-password')
            store.set('test', 'user', 'pass')
            store.save()

            store2 = CredentialStore(path)
            with pytest.raises(Exception):
                store2.unlock('wrong-password')
                store2.get('test')  # Should fail to decrypt
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_list_vendors(self):
        with tempfile.NamedTemporaryFile(suffix='.enc', delete=False) as f:
            path = f.name
        os.unlink(path)

        try:
            store = CredentialStore(path)
            store.unlock('master')
            store.set('vendor1', 'user1', 'pass1')
            store.set('vendor2', 'user2', 'pass2')

            vendors = store.list_vendors()
            assert len(vendors) == 2
            names = [v['vendor'] for v in vendors]
            assert 'vendor1' in names
            assert 'vendor2' in names
            # Verify no passwords are exposed
            for v in vendors:
                assert 'password' not in v
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_delete_vendor(self):
        with tempfile.NamedTemporaryFile(suffix='.enc', delete=False) as f:
            path = f.name
        os.unlink(path)

        try:
            store = CredentialStore(path)
            store.unlock('master')
            store.set('todelete', 'user', 'pass')
            store.delete('todelete')
            assert store.get('todelete') is None
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_locked_store_raises(self):
        store = CredentialStore('/tmp/nonexistent.enc')
        with pytest.raises(RuntimeError, match='locked'):
            store.get('test')

        with pytest.raises(RuntimeError, match='locked'):
            store.set('test', 'user', 'pass')


class TestVendorAPI:
    """Test vendor API endpoints."""

    @pytest.fixture
    def client(self):
        app = create_app(TestConfig)
        with app.app_context():
            db.create_all()
            yield app.test_client()
            db.session.remove()
            db.drop_all()

    def test_list_connectors(self, client):
        response = client.get('/api/vendor/connectors')
        assert response.status_code == 200
        data = response.get_json()
        assert 'connectors' in data
        names = [c['name'] for c in data['connectors']]
        assert 'officeally' in names
        assert 'purview' in names


class TestAnalysisAPI:
    """Test post-import analysis endpoint."""

    @pytest.fixture
    def client(self):
        app = create_app(TestConfig)
        with app.app_context():
            db.create_all()
            yield app.test_client()
            db.session.remove()
            db.drop_all()

    def test_analysis_empty_db(self, client):
        response = client.get('/api/analysis/post-import')
        assert response.status_code == 200
        data = response.get_json()
        assert data['total_records'] == 0
        assert 'recommendations' in data
        assert len(data['recommendations']) > 0

    def test_analysis_with_data(self, client):
        from app.models import BillingRecord, Payer, FeeSchedule
        from datetime import date

        # Seed minimal data
        db.session.add(Payer(code='M/M', display_name='Medicare', filing_deadline_days=365,
                             expected_has_secondary=True))
        if not FeeSchedule.query.filter_by(payer_code='DEFAULT', modality='CT').first():
            db.session.add(FeeSchedule(payer_code='DEFAULT', modality='CT',
                                        expected_rate=395.00, underpayment_threshold=0.80))
        db.session.add(BillingRecord(
            patient_name='SMITH, JOHN', referring_doctor='DOC, TEST',
            scan_type='ABDOMEN', insurance_carrier='M/M', modality='CT',
            service_date=date(2024, 1, 15), total_payment=200.00,
            primary_payment=200.00, secondary_payment=0.0,
            import_source='TEST',
        ))
        db.session.add(BillingRecord(
            patient_name='DOE, JANE', referring_doctor='DOC, TEST',
            scan_type='HEAD', insurance_carrier='M/M', modality='CT',
            service_date=date(2024, 6, 1), total_payment=0.0,
            primary_payment=0.0, secondary_payment=0.0,
            appeal_deadline=date(2024, 12, 1),
            import_source='TEST',
        ))
        db.session.commit()

        response = client.get('/api/analysis/post-import')
        assert response.status_code == 200
        data = response.get_json()
        assert data['total_records'] == 2
        assert data['unpaid_claims'] == 1
        assert data['total_revenue'] == 200.00
        assert 'by_carrier' in data
        assert 'recommendations' in data
        assert len(data['recommendations']) > 0
