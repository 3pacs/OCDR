"""Seed database with payer config, fee schedules, and synthetic demo data."""

import random
from datetime import date, timedelta
from app import create_app
from app.models import db, BillingRecord, Payer, FeeSchedule, Physician

random.seed(42)

# ── Payer configuration ──────────────────────────────────────────
PAYERS = [
    ("M/M", "Medicare / Medicaid", 365, True, 0.25),
    ("CALOPTIMA", "CalOptima Managed Medicaid", 180, True, 0.25),
    ("FAMILY", "Family Health Plan", 180, False, 0.25),
    ("INS", "Commercial Insurance", 180, False, 0.25),
    ("VU PHAN", "Vu Phan Physician Group", 180, False, 0.25),
    ("W/C", "Workers Compensation", 180, False, 0.25),
    ("BEACH", "Beach Clinical Labs", 180, False, 0.25),
    ("ONE CALL", "One Call Care Management", 90, False, 0.50),
    ("OC ADV", "One Call Advanced", 180, False, 0.25),
    ("SELF PAY", "Self Pay / Uninsured", 9999, False, 0.25),
    ("STATE", "State Programs", 365, False, 0.25),
    ("COMP", "Complimentary / Charity", 9999, False, 0.50),
    ("X", "Unknown / Unclassified", 180, False, 0.50),
    ("GH", "Group Health", 180, False, 0.25),
    ("JHANGIANI", "Jhangiani Medical Group", 180, False, 0.25),
]

# ── Fee schedule ─────────────────────────────────────────────────
FEE_SCHEDULES = [
    ("DEFAULT", "CT", 395.00, 0.80),
    ("DEFAULT", "HMRI", 750.00, 0.80),
    ("DEFAULT", "PET", 2500.00, 0.80),
    ("DEFAULT", "BONE", 1800.00, 0.80),
    ("DEFAULT", "OPEN", 750.00, 0.80),
    ("DEFAULT", "DX", 250.00, 0.80),
    ("JHANGIANI", "HMRI", 950.00, 0.80),
]

# ── Physicians ───────────────────────────────────────────────────
PHYSICIANS = [
    ("VU, KHAI", "REFERRING", "Internal Medicine", "Vu Phan Medical"),
    ("JHANGIANI, SURESH", "BOTH", "Oncology / Radiology", "Jhangiani Medical"),
    ("NGUYEN, DAVID", "REFERRING", "Internal Medicine", None),
    ("PATEL, RAJESH", "REFERRING", "Orthopedics", None),
    ("TRAN, MICHAEL", "REFERRING", "Neurology", None),
    ("KIM, JENNIFER", "REFERRING", "Family Medicine", None),
    ("LEE, JAMES", "REFERRING", "Cardiology", None),
    ("GARCIA, MARIA", "REFERRING", "Pulmonology", None),
    ("CHEN, WILLIAM", "REFERRING", "Gastroenterology", None),
    ("PARK, SUSAN", "REFERRING", "Rheumatology", None),
    ("WONG, DANIEL", "REFERRING", "Oncology", None),
    ("SHAH, ANITA", "REFERRING", "Urology", None),
    ("MARTINEZ, CARLOS", "REFERRING", "Pain Management", None),
    ("LIU, JENNY", "REFERRING", "Primary Care", None),
    ("SINGH, HARPREET", "REFERRING", "Neurosurgery", None),
    ("BEACH CLINICAL", "READING", None, "Beach Clinical Labs"),
]

# ── Synthetic billing records ────────────────────────────────────
FIRST_NAMES = [
    "JAMES", "MARY", "ROBERT", "PATRICIA", "JOHN", "JENNIFER", "MICHAEL",
    "LINDA", "DAVID", "ELIZABETH", "WILLIAM", "BARBARA", "RICHARD", "SUSAN",
    "JOSEPH", "JESSICA", "THOMAS", "SARAH", "CHARLES", "KAREN", "DANIEL",
    "LISA", "MATTHEW", "NANCY", "ANTHONY", "BETTY", "MARK", "MARGARET",
    "STEVEN", "SANDRA", "PAUL", "ASHLEY", "ANDREW", "DOROTHY", "JOSHUA",
    "KIMBERLY", "KENNETH", "EMILY", "KEVIN", "DONNA", "BRIAN", "MICHELLE",
    "GEORGE", "CAROL", "TIMOTHY", "AMANDA", "RONALD", "MELISSA", "EDWARD",
    "DEBORAH",
]
LAST_NAMES = [
    "SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES", "GARCIA", "MILLER",
    "DAVIS", "RODRIGUEZ", "MARTINEZ", "HERNANDEZ", "LOPEZ", "GONZALEZ",
    "WILSON", "ANDERSON", "THOMAS", "TAYLOR", "MOORE", "JACKSON", "MARTIN",
    "LEE", "PEREZ", "THOMPSON", "WHITE", "HARRIS", "SANCHEZ", "CLARK",
    "RAMIREZ", "LEWIS", "ROBINSON", "WALKER", "YOUNG", "ALLEN", "KING",
    "WRIGHT", "SCOTT", "TORRES", "NGUYEN", "HILL", "FLORES", "GREEN",
    "ADAMS", "NELSON", "BAKER", "HALL", "RIVERA", "CAMPBELL", "MITCHELL",
    "CARTER", "ROBERTS",
]

SCAN_TYPES = ["ABDOMEN", "CHEST", "HEAD", "CERVICAL", "LUMBAR", "PELVIS",
              "SINUS", "THORACIC", "SHOULDER", "KNEE", "HIP", "BRAIN"]

MODALITIES = ["CT", "HMRI", "PET", "BONE", "OPEN", "DX"]
MODALITY_WEIGHTS = [0.35, 0.30, 0.05, 0.05, 0.10, 0.15]

# Carrier distribution (weighted to match spec numbers)
CARRIER_WEIGHTS = {
    "M/M": 0.38, "CALOPTIMA": 0.12, "FAMILY": 0.10, "INS": 0.12,
    "VU PHAN": 0.07, "W/C": 0.08, "BEACH": 0.02, "ONE CALL": 0.04,
    "OC ADV": 0.01, "SELF PAY": 0.02, "STATE": 0.01, "COMP": 0.005,
    "X": 0.005, "GH": 0.005, "JHANGIANI": 0.015,
}

DOCTORS = [p[0] for p in PHYSICIANS if p[1] in ("REFERRING", "BOTH")]
READERS = ["JHANGIANI, SURESH", "BEACH CLINICAL"]

FEE_MAP = {fs[1]: fs[2] for fs in FEE_SCHEDULES if fs[0] == "DEFAULT"}


def random_date(start_year=2022, end_year=2025):
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def generate_payment(modality, carrier):
    """Generate realistic payment amounts based on modality and carrier."""
    expected = FEE_MAP.get(modality, 395)

    # ~3.6% chance of $0 (unpaid/denied) - results in ~720 of 20000
    if random.random() < 0.036:
        return 0.0, 0.0, 0.0

    # Generate primary payment with realistic variance
    # ~55% of paid claims are underpaid
    if random.random() < 0.55:
        # Underpaid: 30-79% of expected
        pct = random.uniform(0.30, 0.79)
    else:
        # Properly paid: 80-120% of expected
        pct = random.uniform(0.80, 1.20)

    primary = round(expected * pct, 2)

    # Secondary payment for M/M and CALOPTIMA (~60% of those have secondary)
    secondary = 0.0
    if carrier in ("M/M", "CALOPTIMA"):
        if random.random() < 0.40:  # 40% have secondary
            secondary = round(primary * random.uniform(0.05, 0.25), 2)
        # 60% missing secondary = ~1900 claims needing follow-up

    total = round(primary + secondary, 2)
    return primary, secondary, total


def seed():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        # Seed payers
        for code, name, deadline, secondary, threshold in PAYERS:
            db.session.add(Payer(
                code=code, display_name=name,
                filing_deadline_days=deadline,
                expected_has_secondary=secondary,
                alert_threshold_pct=threshold,
            ))

        # Seed fee schedule
        for payer, modality, rate, threshold in FEE_SCHEDULES:
            db.session.add(FeeSchedule(
                payer_code=payer, modality=modality,
                expected_rate=rate, underpayment_threshold=threshold,
            ))

        # Seed physicians
        for name, ptype, spec, clinic in PHYSICIANS:
            db.session.add(Physician(
                name=name, physician_type=ptype,
                specialty=spec, clinic_affiliation=clinic,
            ))

        db.session.commit()

        # Generate ~20,000 synthetic billing records
        carriers = list(CARRIER_WEIGHTS.keys())
        carrier_wts = list(CARRIER_WEIGHTS.values())

        records = []
        for i in range(19936):
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            patient_name = f"{last}, {first}"

            carrier = random.choices(carriers, weights=carrier_wts, k=1)[0]
            modality = random.choices(MODALITIES, weights=MODALITY_WEIGHTS, k=1)[0]
            scan_type = random.choice(SCAN_TYPES)
            doctor = random.choice(DOCTORS)
            reader = random.choice(READERS) if random.random() < 0.7 else None
            svc_date = random_date()
            gado = modality in ("HMRI", "OPEN") and random.random() < 0.60

            primary, secondary, total = generate_payment(modality, carrier)

            # PSMA detection
            is_psma = False
            description = scan_type
            if modality == "PET" and random.random() < 0.08:
                is_psma = True
                description = "PSMA PET/CT"
                if total > 0:
                    primary = round(random.uniform(6000, 10000), 2)
                    secondary = 0.0
                    total = primary

            # C.A.P. bundled scans
            if scan_type in ("CHEST", "ABDOMEN", "PELVIS") and random.random() < 0.03:
                description = "C.A.P"

            # Denial status for $0 claims
            denial_status = None
            denial_reason = None
            if total == 0:
                denial_status = random.choice(
                    ["DENIED", "DENIED", "DENIED", "APPEALED", "WRITTEN_OFF"]
                )
                denial_reason = random.choice(
                    ["CO-4", "CO-16", "CO-45", "PR-1", "PR-2", "CO-97", "CO-18"]
                )

            records.append(BillingRecord(
                patient_name=patient_name,
                referring_doctor=doctor,
                scan_type=scan_type,
                gado_used=gado,
                insurance_carrier=carrier,
                modality=modality,
                service_date=svc_date,
                primary_payment=primary,
                secondary_payment=secondary,
                total_payment=total,
                extra_charges=0.0,
                reading_physician=reader,
                patient_id=10000 + i,
                description=description,
                is_psma=is_psma,
                denial_status=denial_status,
                denial_reason_code=denial_reason,
                import_source="SEED_DATA",
            ))

            # Batch insert every 1000
            if len(records) >= 1000:
                db.session.bulk_save_objects(records)
                db.session.commit()
                records = []

        # Final batch
        if records:
            db.session.bulk_save_objects(records)
            db.session.commit()

        total = BillingRecord.query.count()
        revenue = db.session.query(
            db.func.sum(BillingRecord.total_payment)
        ).scalar() or 0
        unpaid = BillingRecord.query.filter_by(total_payment=0).count()

        print(f"Seeded {total:,} billing records")
        print(f"Total revenue: ${revenue:,.2f}")
        print(f"Unpaid claims: {unpaid:,}")
        print(f"Payers: {Payer.query.count()}")
        print(f"Fee schedules: {FeeSchedule.query.count()}")
        print(f"Physicians: {Physician.query.count()}")


if __name__ == "__main__":
    seed()
