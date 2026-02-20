"""
Unit tests for the document extraction pipeline (schedule + EOB parsers).
Tests the field extraction functions without requiring real PDF files.
"""
from __future__ import annotations

import pytest
from datetime import date, time


class TestScheduleFieldExtraction:
    """Tests for schedule_parser field extraction helpers."""

    def test_extract_date_slash_format(self):
        from app.ingestion.schedule_parser import _extract_date
        result = _extract_date("Appointment on 01/15/2024 at 10:00 AM")
        assert result == date(2024, 1, 15)

    def test_extract_date_dash_format(self):
        from app.ingestion.schedule_parser import _extract_date
        result = _extract_date("Scan Date: 2024-03-22")
        assert result is not None
        assert result.year == 2024
        assert result.month == 3

    def test_extract_date_no_date(self):
        from app.ingestion.schedule_parser import _extract_date
        result = _extract_date("No date information here.")
        assert result is None

    def test_extract_time_am(self):
        from app.ingestion.schedule_parser import _extract_time
        result = _extract_time("Scheduled for 10:30 AM")
        assert result == time(10, 30)

    def test_extract_time_pm(self):
        from app.ingestion.schedule_parser import _extract_time
        result = _extract_time("Appointment at 2:45 PM")
        assert result == time(14, 45)

    def test_extract_time_24hour(self):
        from app.ingestion.schedule_parser import _extract_time
        result = _extract_time("Time: 14:00")
        assert result == time(14, 0)

    def test_extract_time_no_time(self):
        from app.ingestion.schedule_parser import _extract_time
        result = _extract_time("No time information.")
        assert result is None

    def test_extract_modality_mri(self):
        from app.ingestion.schedule_parser import _extract_modality
        result = _extract_modality("MRI Brain with Contrast")
        assert result == "MRI"

    def test_extract_modality_pet_ct(self):
        from app.ingestion.schedule_parser import _extract_modality
        result = _extract_modality("PET/CT Whole Body scan ordered")
        assert result == "PET_CT"

    def test_extract_modality_bone_scan(self):
        from app.ingestion.schedule_parser import _extract_modality
        result = _extract_modality("Nuclear Medicine Bone Scan 3 Phase")
        assert result == "BONE_SCAN"

    def test_extract_modality_ct(self):
        from app.ingestion.schedule_parser import _extract_modality
        result = _extract_modality("CT scan of chest/abdomen/pelvis with contrast")
        assert result == "CT"

    def test_extract_modality_unknown(self):
        from app.ingestion.schedule_parser import _extract_modality
        result = _extract_modality("Some unknown imaging procedure")
        assert result == "OTHER"

    def test_extract_patient_name_label(self):
        from app.ingestion.schedule_parser import _extract_patient_name
        result = _extract_patient_name("Patient: John Smith\nDOB: 01/01/1970")
        assert result == "John Smith"

    def test_extract_patient_name_last_first(self):
        from app.ingestion.schedule_parser import _extract_patient_name
        result = _extract_patient_name("Name: Johnson, Alice\nAppointment: 01/15/2024")
        assert result is not None

    def test_extract_npi(self):
        from app.ingestion.schedule_parser import _extract_npi
        result = _extract_npi("Ordering NPI: 1234567890")
        assert result == "1234567890"

    def test_extract_npi_not_found(self):
        from app.ingestion.schedule_parser import _extract_npi
        result = _extract_npi("No NPI in this text")
        assert result is None

    def test_extract_auth_number(self):
        from app.ingestion.schedule_parser import _extract_auth_number
        result = _extract_auth_number("Authorization: AUTH123456")
        assert result == "AUTH123456"

    def test_extract_physician(self):
        from app.ingestion.schedule_parser import _extract_physician
        result = _extract_physician("Referring Physician: Dr John Smith", "referring")
        assert result is not None


class TestEOBFieldExtraction:
    """Tests for eob_parser field extraction helpers."""

    def test_extract_check_number(self):
        from app.ingestion.eob_parser import _extract_check_info
        result = _extract_check_info("Check #: 123456789\nDate: 03/15/2024")
        assert result.get("check_number") == "123456789"

    def test_extract_check_date(self):
        from app.ingestion.eob_parser import _extract_check_info
        result = _extract_check_info("Check date: 03/15/2024\nTotal: $1,234.56")
        assert result.get("check_date") == date(2024, 3, 15)

    def test_extract_total_paid(self):
        from app.ingestion.eob_parser import _extract_check_info
        result = _extract_check_info("Total Payment: $2,450.00\n")
        assert result.get("total_paid") == 2450.00

    def test_extract_total_paid_no_comma(self):
        from app.ingestion.eob_parser import _extract_check_info
        result = _extract_check_info("Total amount paid: $850.75\n")
        assert result.get("total_paid") == 850.75

    def test_extract_npi(self):
        from app.ingestion.eob_parser import _extract_check_info
        result = _extract_check_info("NPI: 1234567890")
        assert result.get("npi") == "1234567890"

    def test_extract_payer_name(self):
        from app.ingestion.eob_parser import _extract_check_info
        result = _extract_check_info("From: Blue Cross Blue Shield of Illinois\n")
        assert "Blue Cross" in (result.get("payer_name") or "")

    def test_extract_line_items_basic(self):
        from app.ingestion.eob_parser import _extract_line_items
        # Simulate a typical EOB line with date, CPT, billed, allowed, paid
        text = (
            "Patient: John Doe\n"
            "01/15/2024  70553  2500.00  1875.00  1500.00\n"
            "CO-45 375.00  PR-2 375.00"
        )
        items = _extract_line_items(text)
        assert len(items) >= 1
        item = items[0]
        assert item["cpt_code"] == "70553"
        assert item["billed_amount"] == 2500.00
        assert item["allowed_amount"] == 1875.00
        assert item["paid_amount"] == 1500.00

    def test_extract_line_items_empty(self):
        from app.ingestion.eob_parser import _extract_line_items
        items = _extract_line_items("No line items in this text.")
        assert items == []


class TestEncryption:
    """Tests for PHI field encryption/decryption."""

    def test_encrypt_decrypt_ssn(self):
        from app.core.encryption import encrypt_value, decrypt_value
        original = "123-45-6789"
        encrypted = encrypt_value(original)
        assert encrypted != original
        assert len(encrypted) > 20
        decrypted = decrypt_value(encrypted)
        assert decrypted == original

    def test_encrypt_none(self):
        from app.core.encryption import encrypt_value
        assert encrypt_value(None) is None

    def test_decrypt_none(self):
        from app.core.encryption import decrypt_value
        assert decrypt_value(None) is None

    def test_mask_ssn(self):
        from app.core.encryption import mask_value
        masked = mask_value("123456789", visible_chars=4)
        assert masked.endswith("6789")
        assert "1" not in masked[:5]

    def test_mask_short(self):
        from app.core.encryption import mask_value
        masked = mask_value("123", visible_chars=4)
        assert masked == "***"

    def test_decrypt_invalid_raises(self):
        from app.core.encryption import decrypt_value
        with pytest.raises(ValueError):
            decrypt_value("not-valid-ciphertext")


@pytest.mark.asyncio
class TestAPIEndpoints:
    """Smoke tests for critical API endpoints."""

    async def test_health_check(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    async def test_login_success(self, client, auth_headers):
        # auth_headers fixture already logs in — just verify it worked
        assert "Authorization" in auth_headers

    async def test_login_wrong_password(self, client):
        resp = await client.post(
            "/api/v1/auth/token",
            data={"username": "testadmin", "password": "wrong"},
        )
        assert resp.status_code == 401

    async def test_create_patient(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/patients/",
            json={
                "first_name": "Test",
                "last_name": "Patient",
                "dob": "1985-06-15",
                "gender": "M",
                "phone": "555-000-9999",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["first_name"] == "Test"
        assert data["last_name"] == "Patient"
        assert data["mrn"].startswith("MRN-")

    async def test_get_patient_not_found(self, client, auth_headers):
        resp = await client.get("/api/v1/patients/999999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_list_patients(self, client, auth_headers):
        resp = await client.get("/api/v1/patients/?page=1&page_size=10", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    async def test_create_appointment(self, client, auth_headers):
        # First create a patient
        pat_resp = await client.post(
            "/api/v1/patients/",
            json={"first_name": "Appt", "last_name": "Test", "dob": "1990-01-01"},
            headers=auth_headers,
        )
        patient_id = pat_resp.json()["id"]

        appt_resp = await client.post(
            "/api/v1/appointments/",
            json={
                "patient_id": patient_id,
                "scan_date": "2024-06-01",
                "modality": "MRI",
                "body_part": "Brain",
                "status": "scheduled",
            },
            headers=auth_headers,
        )
        assert appt_resp.status_code == 201
        data = appt_resp.json()
        assert data["modality"] == "MRI"
        assert data["patient_id"] == patient_id

    async def test_dashboard_summary(self, client, auth_headers):
        resp = await client.get("/api/v1/reports/dashboard-summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "appointments_today" in data
        assert "revenue" in data

    async def test_unauthorized_access(self, client):
        resp = await client.get("/api/v1/patients/")
        assert resp.status_code == 401

    async def test_fuzzy_search_patients(self, client, auth_headers):
        # Create a patient first
        await client.post(
            "/api/v1/patients/",
            json={"first_name": "Fuzzy", "last_name": "SearchTest", "dob": "1970-01-01"},
            headers=auth_headers,
        )
        resp = await client.get(
            "/api/v1/patients/fuzzy-search?name=Fuzz+Search&threshold=70",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        results = resp.json()
        # Should find our patient
        assert any("Fuzzy" in r["first_name"] for r in results)
