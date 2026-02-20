"""
Unit tests for the multi-pass matching engine.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import date

from app.matching.engine import EOBLineData, MatchResult, _pass1_exact, _pass2_near, _pass3_partial


@pytest.mark.asyncio
class TestPass1ExactMatch:
    async def test_exact_match_by_claim_number_and_dos(self, db_session):
        """Pass 1 matches when claim_number and DOS are both exact."""
        from app.models.patient import Patient
        from app.models.appointment import Appointment
        from app.models.scan import Scan
        from app.models.claim import Claim
        import uuid

        patient = Patient(
            mrn=f"MRN-{uuid.uuid4().hex[:8]}",
            first_name="John",
            last_name="Doe",
            dob=date(1970, 1, 1),
            verification_status="verified",
        )
        db_session.add(patient)
        await db_session.flush()

        appt = Appointment(
            patient_id=patient.id,
            scan_date=date(2024, 1, 15),
            modality="MRI",
            status="completed",
        )
        db_session.add(appt)
        await db_session.flush()

        scan = Scan(
            appointment_id=appt.id,
            accession_number=f"ACC{uuid.uuid4().hex[:6]}",
            cpt_codes=["70553"],
        )
        db_session.add(scan)
        await db_session.flush()

        claim = Claim(
            scan_id=scan.id,
            claim_number="CLM-TEST-001",
            date_of_service=date(2024, 1, 15),
            claim_status="submitted",
        )
        db_session.add(claim)
        await db_session.flush()

        line = EOBLineData(
            patient_name="John Doe",
            date_of_service=date(2024, 1, 15),
            cpt_codes=["70553"],
            claim_number_raw="CLM-TEST-001",
        )
        result = await _pass1_exact(line, db_session)
        assert result.claim_id == claim.id
        assert result.confidence == 100.0
        assert result.pass_number == 1

    async def test_no_match_wrong_claim_number(self, db_session):
        """Pass 1 returns empty result when claim number doesn't match."""
        line = EOBLineData(
            patient_name="Jane Smith",
            date_of_service=date(2024, 2, 1),
            claim_number_raw="WRONG-CLAIM-NUMBER",
        )
        result = await _pass1_exact(line, db_session)
        assert result.claim_id is None
        assert result.confidence == 0.0

    async def test_no_match_without_claim_number(self, db_session):
        """Pass 1 skips when no claim number provided."""
        line = EOBLineData(
            patient_name="Jane Smith",
            date_of_service=date(2024, 2, 1),
            claim_number_raw=None,
        )
        result = await _pass1_exact(line, db_session)
        assert result.claim_id is None


@pytest.mark.asyncio
class TestPass2NearMatch:
    async def test_near_match_high_name_similarity(self, db_session):
        """Pass 2 matches when name similarity ≥90% and DOS exact."""
        from app.models.patient import Patient
        from app.models.appointment import Appointment
        from app.models.scan import Scan
        from app.models.claim import Claim
        import uuid

        patient = Patient(
            mrn=f"MRN-{uuid.uuid4().hex[:8]}",
            first_name="Margaret",
            last_name="Johnson",
            dob=date(1960, 5, 10),
            verification_status="verified",
        )
        db_session.add(patient)
        await db_session.flush()

        appt = Appointment(
            patient_id=patient.id,
            scan_date=date(2024, 3, 20),
            modality="CT",
            status="completed",
        )
        db_session.add(appt)
        await db_session.flush()

        scan = Scan(
            appointment_id=appt.id,
            accession_number=f"ACC{uuid.uuid4().hex[:6]}",
            cpt_codes=["74178"],
        )
        db_session.add(scan)
        await db_session.flush()

        claim = Claim(
            scan_id=scan.id,
            claim_number=f"CLM{uuid.uuid4().hex[:6]}",
            date_of_service=date(2024, 3, 20),
            claim_status="submitted",
        )
        db_session.add(claim)
        await db_session.flush()

        # Slightly misspelled name — common in EOBs
        line = EOBLineData(
            patient_name="Margret Johnson",  # slight misspelling
            date_of_service=date(2024, 3, 20),
            cpt_codes=["74178"],
        )
        result = await _pass2_near(line, db_session)
        assert result.claim_id == claim.id
        assert result.pass_number == 2
        assert result.confidence >= 85.0

    async def test_no_near_match_low_similarity(self, db_session):
        """Pass 2 returns empty result when name similarity < 90%."""
        line = EOBLineData(
            patient_name="XYZ AAA BBB",  # completely different name
            date_of_service=date(2024, 3, 20),
            cpt_codes=["74178"],
        )
        result = await _pass2_near(line, db_session)
        assert result.claim_id is None

    async def test_no_near_match_wrong_dos(self, db_session):
        """Pass 2 requires exact DOS match."""
        line = EOBLineData(
            patient_name="Margaret Johnson",
            date_of_service=date(2099, 1, 1),  # wrong year
            cpt_codes=["74178"],
        )
        result = await _pass2_near(line, db_session)
        assert result.claim_id is None


@pytest.mark.asyncio
class TestPass3PartialMatch:
    async def test_partial_match_dos_within_3_days(self, db_session):
        """Pass 3 matches when name ≥85% and DOS within 3 days."""
        from app.models.patient import Patient
        from app.models.appointment import Appointment
        from app.models.scan import Scan
        from app.models.claim import Claim
        import uuid

        patient = Patient(
            mrn=f"MRN-{uuid.uuid4().hex[:8]}",
            first_name="Robert",
            last_name="Williams",
            dob=date(1955, 7, 22),
            verification_status="verified",
        )
        db_session.add(patient)
        await db_session.flush()

        appt = Appointment(
            patient_id=patient.id,
            scan_date=date(2024, 4, 10),
            modality="BONE_SCAN",
            status="completed",
        )
        db_session.add(appt)
        await db_session.flush()

        scan = Scan(
            appointment_id=appt.id,
            accession_number=f"ACC{uuid.uuid4().hex[:6]}",
            cpt_codes=["78300"],
        )
        db_session.add(scan)
        await db_session.flush()

        claim = Claim(
            scan_id=scan.id,
            claim_number=f"CLM{uuid.uuid4().hex[:6]}",
            date_of_service=date(2024, 4, 10),
            claim_status="submitted",
        )
        db_session.add(claim)
        await db_session.flush()

        # DOS is 2 days off — should still match via pass 3
        line = EOBLineData(
            patient_name="Robert Williams",
            date_of_service=date(2024, 4, 12),  # 2 days later
            cpt_codes=["78300"],
        )
        result = await _pass3_partial(line, db_session)
        assert result.claim_id == claim.id
        assert result.pass_number == 3
        assert result.needs_review is True  # partial always needs review

    async def test_no_partial_match_dos_too_far(self, db_session):
        """Pass 3 does not match when DOS is more than 3 days apart."""
        line = EOBLineData(
            patient_name="Robert Williams",
            date_of_service=date(2024, 4, 20),  # 10 days off
            cpt_codes=["78300"],
        )
        result = await _pass3_partial(line, db_session)
        assert result.claim_id is None


@pytest.mark.asyncio
class TestFullMatchingEngine:
    async def test_full_engine_exact_match(self, db_session):
        """Full engine returns pass 1 for exact claim number match."""
        from app.matching.engine import match_eob_line
        from app.models.patient import Patient
        from app.models.appointment import Appointment
        from app.models.scan import Scan
        from app.models.claim import Claim
        import uuid

        patient = Patient(
            mrn=f"MRN-{uuid.uuid4().hex[:8]}",
            first_name="Linda",
            last_name="Anderson",
            dob=date(1952, 9, 14),
            verification_status="verified",
        )
        db_session.add(patient)
        await db_session.flush()

        appt = Appointment(
            patient_id=patient.id,
            scan_date=date(2024, 5, 5),
            modality="MRI",
            status="completed",
        )
        db_session.add(appt)
        await db_session.flush()

        scan = Scan(
            appointment_id=appt.id,
            accession_number=f"ACC{uuid.uuid4().hex[:6]}",
            cpt_codes=["72148"],
        )
        db_session.add(scan)
        await db_session.flush()

        claim = Claim(
            scan_id=scan.id,
            claim_number="EXACT-CLM-999",
            date_of_service=date(2024, 5, 5),
            claim_status="submitted",
        )
        db_session.add(claim)
        await db_session.flush()

        line = EOBLineData(
            patient_name="Linda Anderson",
            date_of_service=date(2024, 5, 5),
            cpt_codes=["72148"],
            claim_number_raw="EXACT-CLM-999",
        )
        result = await match_eob_line(line, db_session)
        assert result.pass_number == 1
        assert result.claim_id == claim.id

    async def test_full_engine_manual_queue_fallback(self, db_session):
        """Full engine falls through to manual queue when no match exists."""
        from app.matching.engine import match_eob_line

        line = EOBLineData(
            patient_name="Totally Unknown Patient XYZ",
            date_of_service=date(2099, 12, 31),
            cpt_codes=["99999"],
            claim_number_raw="NONEXISTENT-CLM",
        )
        result = await match_eob_line(line, db_session)
        assert result.pass_number == 4
        assert result.pass_name == "manual_queue"
        assert result.needs_review is True
        assert result.claim_id is None
