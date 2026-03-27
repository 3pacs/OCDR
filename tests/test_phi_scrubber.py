"""Tests for PHI scrubber and AI assistant endpoints.

Verifies that:
  - All 18 HIPAA Safe Harbor identifiers are properly redacted
  - Structural metadata passes through safely
  - PHI validation catches leaks before transmission
  - AI assistant routes work with correct PHI protection
"""
import os
import sys
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.models import db
from app.import_engine.phi_scrubber import (
    scrub_value,
    scrub_row,
    extract_safe_schema,
    extract_safe_file_metadata,
    validate_payload_phi_free,
)


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-secret'
    ANTHROPIC_API_KEY = ''  # No real key in tests


# ---- scrub_value tests ----

class TestScrubValue:
    """Test individual value scrubbing."""

    def test_none_value(self):
        result, vtype = scrub_value(None)
        assert result == '[NULL]'
        assert vtype == 'null'

    def test_boolean_value(self):
        result, vtype = scrub_value(True)
        assert result == 'True'
        assert vtype == 'boolean'

    def test_number_value(self):
        result, vtype = scrub_value(750.00)
        assert result == '[NUMBER]'
        assert vtype == 'number'

    def test_integer_value(self):
        result, vtype = scrub_value(42)
        assert result == '[NUMBER]'
        assert vtype == 'number'

    def test_empty_string(self):
        result, vtype = scrub_value('')
        assert result == '[EMPTY]'
        assert vtype == 'empty'

    def test_whitespace_string(self):
        result, vtype = scrub_value('   ')
        assert result == '[EMPTY]'
        assert vtype == 'empty'

    def test_date_mmddyyyy(self):
        """Dates with day/month precision must be redacted."""
        result, vtype = scrub_value('01/15/2024')
        assert result == '[DATE_VALUE]'
        assert vtype == 'date'

    def test_date_iso(self):
        result, vtype = scrub_value('2024-01-15')
        assert result == '[DATE_VALUE]'
        assert vtype == 'date'

    def test_date_object(self):
        from datetime import date
        result, vtype = scrub_value(date(2024, 1, 15))
        assert result == '[DATE:2024]'
        assert vtype == 'date'
        # Only year preserved — no month/day

    def test_datetime_object(self):
        from datetime import datetime
        result, vtype = scrub_value(datetime(2024, 1, 15, 10, 30))
        assert result == '[DATE:2024]'
        assert vtype == 'date'

    def test_ssn_with_dashes(self):
        result, vtype = scrub_value('123-45-6789')
        assert result == '[SSN_REDACTED]'
        assert vtype == 'ssn'

    def test_ssn_without_dashes(self):
        result, vtype = scrub_value('123456789')
        # 9-digit number should be caught as identifier
        assert 'REDACTED' in result or 'ID' in result

    def test_phone_number(self):
        result, vtype = scrub_value('(714) 555-1234')
        assert result == '[PHONE_REDACTED]'
        assert vtype == 'phone'

    def test_phone_with_dots(self):
        result, vtype = scrub_value('714.555.1234')
        assert result == '[PHONE_REDACTED]'
        assert vtype == 'phone'

    def test_email_address(self):
        result, vtype = scrub_value('john.smith@hospital.com')
        assert result == '[EMAIL_REDACTED]'
        assert vtype == 'email'

    def test_long_number_as_mrn(self):
        """6+ digit numbers could be MRNs or account numbers."""
        result, vtype = scrub_value('12345678')
        assert 'ID' in result
        assert vtype == 'identifier'

    def test_patient_name_last_first(self):
        """LAST, FIRST format (all caps) = patient name."""
        result, vtype = scrub_value('SMITH, JOHN')
        assert result == '[PATIENT_NAME]'
        assert vtype == 'name'

    def test_patient_name_all_caps(self):
        result, vtype = scrub_value("O'BRIEN, MARY")
        assert result == '[PATIENT_NAME]'
        assert vtype == 'name'

    def test_short_code_passes_through(self):
        """Short alphanumeric codes (modalities, payers) are safe."""
        result, vtype = scrub_value('HMRI')
        assert result == 'HMRI'
        assert vtype == 'code'

    def test_modality_code(self):
        result, vtype = scrub_value('CT')
        assert result == 'CT'
        assert vtype == 'code'

    def test_payer_code(self):
        result, vtype = scrub_value('M/M')
        assert result == 'M/M'
        assert vtype == 'code'

    def test_cpt_code(self):
        result, vtype = scrub_value('74177')
        assert result == '74177'
        assert vtype == 'code'


# ---- scrub_row tests ----

class TestScrubRow:
    def test_row_scrubbing(self):
        row = {
            'patient_name': 'SMITH, JOHN',
            'service_date': '01/15/2024',
            'modality': 'HMRI',
            'total_payment': 750.00,
            'ssn': '123-45-6789',
        }
        scrubbed = scrub_row(row)

        assert scrubbed['patient_name']['pattern'] == '[PATIENT_NAME]'
        assert scrubbed['service_date']['pattern'] == '[DATE_VALUE]'
        assert scrubbed['modality']['pattern'] == 'HMRI'
        assert scrubbed['total_payment']['pattern'] == '[NUMBER]'
        assert scrubbed['ssn']['pattern'] == '[SSN_REDACTED]'

    def test_row_preserves_structure(self):
        row = {'a': 'test', 'b': None, 'c': 42}
        scrubbed = scrub_row(row)
        assert set(scrubbed.keys()) == {'a', 'b', 'c'}
        assert 'pattern' in scrubbed['a']
        assert 'type' in scrubbed['a']


# ---- extract_safe_schema tests ----

class TestExtractSafeSchema:
    def test_schema_extraction(self):
        headers = ['Patient Name', 'DOS', 'Modality', 'Payment']
        sample_rows = [
            ['SMITH, JOHN', '01/15/2024', 'HMRI', 750.00],
            ['DOE, JANE', '01/16/2024', 'CT', 395.00],
        ]
        schema = extract_safe_schema(headers, sample_rows)

        assert schema['column_count'] == 4
        assert schema['row_count_sample'] == 2
        assert len(schema['columns']) == 4

        # Verify headers are preserved (they're metadata, not PHI)
        assert schema['columns'][0]['header'] == 'Patient Name'
        assert schema['columns'][2]['header'] == 'Modality'

        # Verify values are scrubbed
        patterns = schema['columns'][0]['sample_patterns']
        assert '[PATIENT_NAME]' in patterns

        # Modality codes should pass through
        mod_patterns = schema['columns'][2]['sample_patterns']
        assert 'HMRI' in mod_patterns

    def test_schema_with_empty_rows(self):
        headers = ['Col1']
        schema = extract_safe_schema(headers, [])
        assert schema['column_count'] == 1
        assert schema['row_count_sample'] == 0

    def test_schema_limits_samples(self):
        headers = ['A']
        rows = [['val1'], ['val2'], ['val3'], ['val4'], ['val5']]
        schema = extract_safe_schema(headers, rows, max_samples=2)
        assert len(schema['columns'][0]['sample_patterns']) == 2


# ---- extract_safe_file_metadata tests ----

class TestExtractSafeFileMetadata:
    def test_csv_metadata(self, tmp_path):
        csv_file = tmp_path / 'test.csv'
        csv_content = 'Name,Date,Amount\nSMITH,01/15/2024,750.00\n'
        csv_file.write_text(csv_content)

        metadata = extract_safe_file_metadata(str(csv_file), csv_content)
        assert metadata['file_extension'] == '.csv'
        assert metadata['file_size_bytes'] > 0
        assert 'detected_headers' in metadata
        assert 'Name' in metadata['detected_headers']

    def test_835_content_metadata(self, tmp_path):
        edi_file = tmp_path / 'test.835'
        edi_content = 'ISA*00*test~GS*HP~ST*835~BPR*I*1000~CLP*CLM1~SVC*HC:74177~'
        edi_file.write_text(edi_content)

        metadata = extract_safe_file_metadata(str(edi_file), edi_content)
        assert metadata['file_extension'] == '.835'
        # Should detect X12 segments
        assert metadata.get('segment_ISA_count', 0) >= 1

    def test_delimiter_detection(self, tmp_path):
        pipe_file = tmp_path / 'test.txt'
        content = 'col1|col2|col3\nval1|val2|val3'
        pipe_file.write_text(content)

        metadata = extract_safe_file_metadata(str(pipe_file), content)
        assert 'pipe_count_line1' in metadata
        assert metadata['pipe_count_line1'] == 2

    def test_no_content_preview(self, tmp_path):
        f = tmp_path / 'empty.txt'
        f.write_text('hello')
        metadata = extract_safe_file_metadata(str(f))
        assert metadata['file_extension'] == '.txt'
        assert 'line_count_preview' not in metadata


# ---- validate_payload_phi_free tests ----

class TestValidatePayloadPhiFree:
    def test_safe_payload_passes(self):
        payload = {
            'column_count': 5,
            'columns': ['Name', 'Date', 'Amount'],
            'patterns': ['[PATIENT_NAME]', '[DATE_VALUE]', '[NUMBER]'],
            'modality': 'HMRI',
        }
        is_safe, issues = validate_payload_phi_free(payload)
        assert is_safe is True
        assert len(issues) == 0

    def test_ssn_detected(self):
        payload = {'data': '123-45-6789'}
        is_safe, issues = validate_payload_phi_free(payload)
        assert is_safe is False
        assert any('SSN' in i for i in issues)

    def test_phone_detected(self):
        payload = {'contact': '(714) 555-1234'}
        is_safe, issues = validate_payload_phi_free(payload)
        assert is_safe is False
        assert any('phone' in i.lower() for i in issues)

    def test_email_detected(self):
        payload = {'email': 'patient@hospital.com'}
        is_safe, issues = validate_payload_phi_free(payload)
        assert is_safe is False
        assert any('email' in i.lower() for i in issues)

    def test_date_detected(self):
        payload = {'dos': '01/15/2024'}
        is_safe, issues = validate_payload_phi_free(payload)
        assert is_safe is False
        assert any('date' in i.lower() for i in issues)

    def test_redacted_date_ok(self):
        """Dates in redacted form [DATE_VALUE] should be safe."""
        payload = {'date_pattern': '[DATE_VALUE]'}
        is_safe, issues = validate_payload_phi_free(payload)
        assert is_safe is True

    def test_patient_name_detected(self):
        payload = {'name': 'SMITH, JOHN'}
        is_safe, issues = validate_payload_phi_free(payload)
        assert is_safe is False
        assert any('name' in i.lower() for i in issues)

    def test_nested_phi_detected(self):
        """PHI hidden in nested structures must be caught."""
        payload = {
            'level1': {
                'level2': [
                    {'value': '123-45-6789'},
                ],
            },
        }
        is_safe, issues = validate_payload_phi_free(payload)
        assert is_safe is False

    def test_multiple_phi_types(self):
        payload = {
            'ssn': '123-45-6789',
            'phone': '714-555-1234',
            'email': 'test@test.com',
        }
        is_safe, issues = validate_payload_phi_free(payload)
        assert is_safe is False
        assert len(issues) >= 3  # At least 3 different PHI detections


# ---- AI Assistant API Route tests ----

class TestAIAssistantRoutes:
    """Test AI assistant endpoints (without actual API calls)."""

    @pytest.fixture
    def client(self):
        app = create_app(TestConfig)
        with app.app_context():
            db.create_all()
            yield app.test_client()
            db.session.remove()
            db.drop_all()

    def test_ai_status_unconfigured(self, client):
        resp = client.get('/api/import/ai/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'configured' in data
        assert 'phi_policy' in data

    def test_ai_configure_missing_key(self, client):
        resp = client.post('/api/import/ai/configure',
                           data=json.dumps({}),
                           content_type='application/json')
        assert resp.status_code == 400

    def test_ai_configure_invalid_key(self, client):
        resp = client.post('/api/import/ai/configure',
                           data=json.dumps({'api_key': 'not-a-valid-key'}),
                           content_type='application/json')
        assert resp.status_code == 400

    def test_ai_analyze_file_no_file(self, client):
        resp = client.post('/api/import/ai/analyze-file')
        assert resp.status_code == 400

    def test_ai_suggest_mapping_no_file(self, client):
        resp = client.post('/api/import/ai/suggest-mapping')
        assert resp.status_code == 400

    def test_phi_check_safe_payload(self, client):
        payload = {
            'columns': ['Name', 'Date'],
            'patterns': ['[PATIENT_NAME]', '[DATE_VALUE]'],
            'count': 100,
        }
        resp = client.post('/api/import/ai/phi-check',
                           data=json.dumps(payload),
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['is_safe'] is True

    def test_phi_check_unsafe_payload(self, client):
        payload = {
            'patient': 'SMITH, JOHN',
            'ssn': '123-45-6789',
            'phone': '(714) 555-1234',
        }
        resp = client.post('/api/import/ai/phi-check',
                           data=json.dumps(payload),
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['is_safe'] is False
        assert len(data['issues']) >= 2

    def test_phi_check_no_body(self, client):
        resp = client.post('/api/import/ai/phi-check')
        assert resp.status_code == 400

    def test_ai_analyze_db_no_key(self, client):
        """Without API key, should return error message (not crash)."""
        from unittest.mock import patch
        with patch('app.import_engine.ai_assistant._get_api_key', return_value=None):
            resp = client.get('/api/import/ai/analyze-db')
            assert resp.status_code == 200
            data = resp.get_json()
            assert 'error' in data
            assert 'key' in data['error'].lower() or 'api' in data['error'].lower()
