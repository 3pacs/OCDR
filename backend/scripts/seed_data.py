#!/usr/bin/env python3
"""
Seed data script — creates 10 sample patients, appointments, scans, claims,
insurance records, EOBs, and payments for testing and development.

Usage:
    cd backend
    python scripts/seed_data.py
"""
from __future__ import annotations

import asyncio
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.encryption import encrypt_value
from app.core.security import hash_password
from app.database import AsyncSessionLocal, create_all_tables
import app.models  # noqa: F401


# ── Sample data ───────────────────────────────────────────────────────────────

SAMPLE_PATIENTS = [
    {"first": "Alice", "last": "Johnson", "dob": date(1978, 3, 15), "gender": "F",
     "phone": "555-201-0001", "email": "alice.j@email.com", "ssn": "123-45-6789",
     "address": "123 Maple St", "city": "Springfield", "state": "IL", "zip": "62701"},
    {"first": "Robert", "last": "Williams", "dob": date(1955, 7, 22), "gender": "M",
     "phone": "555-201-0002", "email": "r.williams@email.com", "ssn": "234-56-7890",
     "address": "456 Oak Ave", "city": "Peoria", "state": "IL", "zip": "61602"},
    {"first": "Maria", "last": "Garcia", "dob": date(1962, 11, 5), "gender": "F",
     "phone": "555-201-0003", "email": "m.garcia@email.com", "ssn": "345-67-8901",
     "address": "789 Pine Rd", "city": "Rockford", "state": "IL", "zip": "61101"},
    {"first": "James", "last": "Thompson", "dob": date(1945, 1, 30), "gender": "M",
     "phone": "555-201-0004", "ssn": "456-78-9012",
     "address": "321 Elm St", "city": "Aurora", "state": "IL", "zip": "60505"},
    {"first": "Patricia", "last": "Davis", "dob": date(1970, 8, 18), "gender": "F",
     "phone": "555-201-0005", "email": "pdavis@email.com", "ssn": "567-89-0123",
     "address": "654 Birch Ln", "city": "Joliet", "state": "IL", "zip": "60432"},
    {"first": "Michael", "last": "Martinez", "dob": date(1988, 4, 2), "gender": "M",
     "phone": "555-201-0006", "email": "mike.m@email.com", "ssn": "678-90-1234",
     "address": "987 Cedar Dr", "city": "Naperville", "state": "IL", "zip": "60540"},
    {"first": "Linda", "last": "Anderson", "dob": date(1952, 9, 14), "gender": "F",
     "phone": "555-201-0007", "ssn": "789-01-2345",
     "address": "147 Spruce Way", "city": "Champaign", "state": "IL", "zip": "61820"},
    {"first": "David", "last": "Wilson", "dob": date(1967, 6, 25), "gender": "M",
     "phone": "555-201-0008", "email": "d.wilson@email.com", "ssn": "890-12-3456",
     "address": "258 Walnut Ct", "city": "Decatur", "state": "IL", "zip": "62521"},
    {"first": "Barbara", "last": "Taylor", "dob": date(1940, 12, 3), "gender": "F",
     "phone": "555-201-0009", "ssn": "901-23-4567",
     "address": "369 Hickory Pl", "city": "Bloomington", "state": "IL", "zip": "61701"},
    {"first": "Christopher", "last": "Lee", "dob": date(1995, 2, 28), "gender": "M",
     "phone": "555-201-0010", "email": "chris.lee@email.com", "ssn": "012-34-5678",
     "address": "741 Magnolia Blvd", "city": "Evanston", "state": "IL", "zip": "60201"},
]

PAYERS = [
    ("Blue Cross Blue Shield", "BCBS001", "PPO Gold"),
    ("Aetna", "AETNA001", "HMO Silver"),
    ("UnitedHealthcare", "UHC001", "Choice Plus"),
    ("Medicare", "MEDICARE", "Part B"),
    ("Medicaid", "MEDICAID", "MCO Standard"),
]

MODALITIES = ["MRI", "PET_CT", "BONE_SCAN", "CT", "MRI"]
BODY_PARTS = [
    "Brain with contrast", "Whole body PET/CT", "Whole body bone scan",
    "Chest/Abdomen/Pelvis", "Lumbar spine", "Knee right", "Knee left",
    "Pelvis with contrast", "Cervical spine", "Cardiac PET"
]
CPT_CODES = {
    "MRI": [["70553"], ["72148"], ["73721"]],
    "PET_CT": [["78816"], ["78815"]],
    "BONE_SCAN": [["78300"], ["78315"]],
    "CT": [["74178"], ["74177"], ["71250"]],
}
PHYSICIANS = [
    "Dr. Sarah Chen", "Dr. Mark Patel", "Dr. Jennifer Wong",
    "Dr. Thomas Reed", "Dr. Angela Vasquez"
]
RADIOLOGISTS = [
    "Dr. Howard Kim", "Dr. Lisa Park", "Dr. David Nguyen"
]
TECHNOLOGISTS = ["Alex Smith", "Jamie Rodriguez", "Taylor Brown"]


async def seed(db: AsyncSession) -> None:
    from app.models.user import User
    from app.models.patient import Patient
    from app.models.insurance import Insurance
    from app.models.appointment import Appointment
    from app.models.scan import Scan
    from app.models.claim import Claim
    from app.models.payment import Payment
    from app.models.eob import EOB, EOBLineItem
    from app.models.reconciliation import Reconciliation
    from app.models.learning import BusinessRule

    print("Creating users...")
    users = [
        User(username="admin", email="admin@ocdr.local", full_name="System Admin",
             role="admin", hashed_password=hash_password("Admin123!"), is_active=True),
        User(username="biller1", email="biller@ocdr.local", full_name="Jane Biller",
             role="biller", hashed_password=hash_password("Biller123!"), is_active=True),
        User(username="frontdesk", email="frontdesk@ocdr.local", full_name="Bob Front",
             role="front_desk", hashed_password=hash_password("Desk123!"), is_active=True),
        User(username="readonly", email="readonly@ocdr.local", full_name="Read Only User",
             role="read_only", hashed_password=hash_password("Read123!"), is_active=True),
    ]
    for u in users:
        db.add(u)
    await db.flush()
    print(f"  Created {len(users)} users")

    print("Creating patients, insurance, appointments, scans, claims, payments...")
    today = date.today()
    patient_records = []

    for i, pt_data in enumerate(SAMPLE_PATIENTS):
        # Patient
        patient = Patient(
            mrn=f"MRN-{uuid.uuid4().hex[:8].upper()}",
            first_name=pt_data["first"],
            last_name=pt_data["last"],
            dob=pt_data["dob"],
            gender=pt_data.get("gender"),
            address_line1=pt_data.get("address"),
            city=pt_data.get("city"),
            state=pt_data.get("state"),
            zip_code=pt_data.get("zip"),
            phone=pt_data.get("phone"),
            email=pt_data.get("email"),
            ssn_encrypted=encrypt_value(pt_data.get("ssn")) if pt_data.get("ssn") else None,
            verification_status="verified",
            source_file="seed_data.py",
            extraction_confidence=99.0,
        )
        db.add(patient)
        await db.flush()
        patient_records.append(patient)

        # Insurance (primary)
        payer = random.choice(PAYERS)
        ins = Insurance(
            patient_id=patient.id,
            payer_name=payer[0],
            payer_id=payer[1],
            plan_name=payer[2],
            member_id=f"MBR{random.randint(100000, 999999)}",
            group_number=f"GRP{random.randint(10000, 99999)}",
            subscriber_name=f"{pt_data['first']} {pt_data['last']}",
            relationship_to_patient="self",
            copay=random.choice([20.0, 30.0, 50.0]),
            deductible=random.choice([500.0, 1000.0, 2500.0]),
            out_of_pocket_max=random.choice([3000.0, 5000.0, 7500.0]),
            authorization_number=f"AUTH{random.randint(100000, 999999)}" if random.random() > 0.4 else None,
            authorization_start_date=today - timedelta(days=30),
            authorization_end_date=today + timedelta(days=180),
            is_primary=True,
            is_active=True,
            eligibility_verified=True,
            eligibility_verified_at=today - timedelta(days=1),
        )
        db.add(ins)
        await db.flush()

        # Appointments (2-3 per patient, spread across past 90 days)
        for j in range(random.randint(2, 3)):
            appt_date = today - timedelta(days=random.randint(0, 90))
            modality = MODALITIES[i % len(MODALITIES)]
            cpt_list = CPT_CODES.get(modality, [["99213"]])
            cpt_codes = random.choice(cpt_list)

            appt = Appointment(
                patient_id=patient.id,
                scan_date=appt_date,
                scan_time=time(random.randint(8, 16), random.choice([0, 15, 30, 45])),
                modality=modality,
                body_part=random.choice(BODY_PARTS),
                referring_physician=random.choice(PHYSICIANS),
                ordering_physician=random.choice(PHYSICIANS),
                ordering_npi=f"{random.randint(1000000000, 9999999999)}",
                facility_location="OCDR Main Center — Suite 100",
                technologist=random.choice(TECHNOLOGISTS),
                status="completed" if appt_date < today else "scheduled",
                notes="Routine imaging per referring physician order.",
                source_file="seed_schedule_01.pdf",
                extraction_confidence=92.0,
            )
            db.add(appt)
            await db.flush()

            if appt.status == "completed":
                # Scan
                scan = Scan(
                    appointment_id=appt.id,
                    accession_number=f"ACC{uuid.uuid4().hex[:8].upper()}",
                    study_description=" ".join(cpt_codes) + f" — {appt.body_part}",
                    radiologist=random.choice(RADIOLOGISTS),
                    report_status="final",
                    cpt_codes=cpt_codes,
                    units=1,
                    charges=random.uniform(800, 3500),
                )
                db.add(scan)
                await db.flush()

                # Claim
                billed = round(scan.charges or 1000.0, 2)
                allowed = round(billed * random.uniform(0.65, 0.85), 2)
                paid = round(allowed * random.uniform(0.70, 0.95), 2)
                patient_resp = round(allowed - paid, 2)

                statuses = ["paid", "paid", "paid", "partial", "pending", "denied"]
                cl_status = random.choice(statuses)

                claim = Claim(
                    scan_id=scan.id,
                    insurance_id=ins.id,
                    claim_number=f"CLM{uuid.uuid4().hex[:8].upper()}",
                    date_of_service=appt.scan_date,
                    date_submitted=appt.scan_date + timedelta(days=random.randint(1, 5)),
                    billed_amount=billed,
                    allowed_amount=allowed if cl_status not in ("pending",) else None,
                    paid_amount=paid if cl_status in ("paid", "partial") else None,
                    adjustment_amount=round(billed - allowed, 2) if cl_status in ("paid", "partial") else None,
                    patient_responsibility=patient_resp if cl_status in ("paid", "partial") else None,
                    claim_status=cl_status,
                    denial_code="CO-97" if cl_status == "denied" else None,
                    denial_reason="Service not covered by plan" if cl_status == "denied" else None,
                )
                db.add(claim)
                await db.flush()

                # EOB (for paid claims)
                if cl_status in ("paid", "partial"):
                    eob = EOB(
                        raw_file_path=f"/data/eobs/processed/EOB_{uuid.uuid4().hex[:6]}.pdf",
                        file_type="pdf",
                        payer_name=payer[0],
                        payer_id=payer[1],
                        check_number=f"CHK{random.randint(100000, 999999)}",
                        check_date=appt.scan_date + timedelta(days=random.randint(14, 45)),
                        total_paid=paid,
                        processed_status="processed",
                        processed_at=datetime.now(timezone.utc),
                        matched_claim_ids=[claim.id],
                        confidence_score=94.0,
                        extraction_method="pdfplumber",
                    )
                    db.add(eob)
                    await db.flush()

                    line_item = EOBLineItem(
                        eob_id=eob.id,
                        claim_id=claim.id,
                        patient_name_raw=f"{patient.first_name} {patient.last_name}",
                        date_of_service=appt.scan_date,
                        cpt_code=cpt_codes[0],
                        units=1,
                        billed_amount=billed,
                        allowed_amount=allowed,
                        paid_amount=paid,
                        patient_responsibility=patient_resp,
                        adjustment_codes=[{"code": "CO-45", "amount": round(billed - allowed, 2)}],
                        match_confidence=94.0,
                        match_pass="near_match",
                        match_status="matched",
                    )
                    db.add(line_item)

                    payment = Payment(
                        patient_id=patient.id,
                        claim_id=claim.id,
                        eob_id=eob.id,
                        payment_date=eob.check_date,
                        payment_type="insurance_check",
                        amount=paid,
                        check_number=eob.check_number,
                        eob_source_file=eob.raw_file_path,
                        posting_status="posted",
                        posted_by="biller1",
                        posted_date=datetime.now(timezone.utc),
                        match_confidence=94.0,
                        match_pass="near_match",
                    )
                    db.add(payment)

                    recon = Reconciliation(
                        claim_id=claim.id,
                        expected_payment=allowed,
                        actual_payment=paid,
                        variance=round(allowed - paid, 2),
                        variance_pct=round((allowed - paid) / allowed * 100, 1) if allowed else 0,
                        reconciliation_status="matched" if abs(allowed - paid) <= 10 else "partial",
                        flagged_for_review=abs(allowed - paid) > 10,
                    )
                    db.add(recon)

    # Business rules
    print("Creating sample business rules...")
    rules = [
        BusinessRule(
            rule_name="BCBS MRI Brain",
            payer_name="Blue Cross Blue Shield",
            payer_id="BCBS001",
            cpt_code="70553",
            rule_type="pct_of_billed",
            rule_params={"percentage": 0.78},
            description="BCBS pays 78% of billed for CPT 70553",
            is_active=True,
            created_by="admin",
        ),
        BusinessRule(
            rule_name="Medicare PET/CT",
            payer_name="Medicare",
            payer_id="MEDICARE",
            cpt_code="78816",
            rule_type="pct_of_billed",
            rule_params={"percentage": 0.80},
            description="Medicare pays 80% of billed for whole body PET/CT",
            is_active=True,
            created_by="admin",
        ),
    ]
    for rule in rules:
        db.add(rule)

    await db.flush()
    print("Seed data committed successfully.")


async def main():
    print("=" * 60)
    print("OCDR Seed Data Script")
    print("=" * 60)
    print(f"Database: {settings.DATABASE_URL[:50]}...")
    print()

    print("Ensuring tables exist...")
    await create_all_tables()

    async with AsyncSessionLocal() as db:
        try:
            await seed(db)
            await db.commit()
            print()
            print("Seed complete!")
            print()
            print("Login credentials:")
            print("  Admin:      admin / Admin123!")
            print("  Biller:     biller1 / Biller123!")
            print("  Front desk: frontdesk / Desk123!")
            print("  Read only:  readonly / Read123!")
        except Exception as exc:
            await db.rollback()
            print(f"Error during seeding: {exc}")
            raise


if __name__ == "__main__":
    asyncio.run(main())
