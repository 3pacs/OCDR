"""Seed the database with payer config, fee schedule, and synthetic test claims."""

import random
from datetime import date, timedelta

from app import create_app, get_db

PAYERS = [
    ('M/M',       'Medicare/Medicaid',              365, True,  0.25),
    ('CALOPTIMA', 'CalOptima Managed Medicaid',      180, True,  0.25),
    ('FAMILY',    'Family Health Plan',              180, False, 0.25),
    ('INS',       'Commercial Insurance (General)',  180, False, 0.25),
    ('VU PHAN',   'Vu Phan Physician Group',         180, False, 0.25),
    ('W/C',       'Workers Compensation',            180, False, 0.25),
    ('BEACH',     'Beach Clinical Labs',             180, False, 0.25),
    ('ONE CALL',  'One Call Care Management',         90, False, 0.50),
    ('OC ADV',    'One Call Advanced',               180, False, 0.25),
    ('SELF PAY',  'Self Pay / Uninsured',           9999, False, 0.25),
    ('STATE',     'State Programs',                  365, False, 0.25),
    ('COMP',      'Complimentary / Charity',        9999, False, 0.50),
    ('X',         'Unknown / Unclassified',          180, False, 0.50),
    ('GH',        'Group Health',                    180, False, 0.25),
]

FEE_SCHEDULE = [
    ('DEFAULT', 'CT',   395.00, 0.80),
    ('DEFAULT', 'HMRI', 750.00, 0.80),
    ('DEFAULT', 'PET',  2500.00, 0.80),
    ('DEFAULT', 'BONE', 1800.00, 0.80),
    ('DEFAULT', 'OPEN', 750.00, 0.80),
    ('DEFAULT', 'DX',   250.00, 0.80),
]

# Synthetic test data pools
PATIENTS = [
    'COPE, CURTIS', 'SMITH, JANE', 'NGUYEN, DAVID', 'GARCIA, MARIA',
    'JOHNSON, ROBERT', 'LEE, SARAH', 'PATEL, AMIT', 'BROWN, LISA',
    'WILLIAMS, JAMES', 'JONES, EMILY', 'MILLER, CHRIS', 'DAVIS, ANNA',
    'WILSON, MARK', 'MOORE, JESSICA', 'TAYLOR, DANIEL', 'ANDERSON, RACHEL',
    'THOMAS, KEVIN', 'JACKSON, LAURA', 'WHITE, STEVEN', 'HARRIS, NICOLE',
]

DOCTORS = [
    'VU, KHAI', 'JHANGIANI, SUNIL', 'BEACH, MICHAEL', 'PHAM, TUNG',
    'CHEN, DAVID', 'RAMIREZ, CARLOS', 'KIM, YOON', 'SHAH, PRIYA',
]

SCANS = ['ABDOMEN', 'CHEST', 'HEAD', 'CERVICAL', 'LUMBAR', 'PELVIS', 'SINUS']
MODALITIES = ['CT', 'HMRI', 'PET', 'BONE', 'OPEN', 'DX']
DENIAL_REASONS = ['CO-4', 'CO-16', 'CO-45', 'PR-1', 'PR-2', 'PR-3', 'CO-97', 'OA-23']
CARRIER_CODES = ['M/M', 'CALOPTIMA', 'FAMILY', 'INS', 'W/C', 'ONE CALL']


def seed():
    app = create_app()
    with app.app_context():
        db = get_db()

        # Seed payers
        db.executemany(
            "INSERT OR IGNORE INTO payers (code, display_name, filing_deadline_days, expected_has_secondary, alert_threshold_pct) VALUES (?,?,?,?,?)",
            PAYERS,
        )

        # Seed fee schedule
        db.executemany(
            "INSERT OR IGNORE INTO fee_schedule (payer_code, modality, expected_rate, underpayment_threshold) VALUES (?,?,?,?)",
            FEE_SCHEDULE,
        )

        # Generate synthetic claims
        random.seed(42)
        today = date.today()
        claims = []

        for i in range(200):
            patient = random.choice(PATIENTS)
            doctor = random.choice(DOCTORS)
            scan = random.choice(SCANS)
            modality = random.choice(MODALITIES)
            carrier = random.choice(CARRIER_CODES)
            days_ago = random.randint(10, 400)
            svc_date = today - timedelta(days=days_ago)

            # Determine payment scenario
            scenario = random.choices(
                ['paid', 'underpaid', 'denied', 'unpaid_no_secondary'],
                weights=[40, 20, 25, 15],
            )[0]

            fee_map = dict(CT=395, HMRI=750, PET=2500, BONE=1800, OPEN=750, DX=250)
            expected = fee_map.get(modality, 395)

            if scenario == 'paid':
                primary = round(expected * random.uniform(0.85, 1.1), 2)
                secondary = round(random.uniform(20, 100), 2) if carrier in ('M/M', 'CALOPTIMA') else 0
                total = round(primary + secondary, 2)
                denial_status = None
                denial_reason = None
            elif scenario == 'underpaid':
                primary = round(expected * random.uniform(0.3, 0.7), 2)
                secondary = 0
                total = primary
                denial_status = None
                denial_reason = None
            elif scenario == 'denied':
                primary = 0
                secondary = 0
                total = 0
                denial_status = random.choice(['DENIED', 'DENIED', 'DENIED', 'APPEALED'])
                denial_reason = random.choice(DENIAL_REASONS)
            else:  # unpaid_no_secondary
                primary = round(expected * random.uniform(0.8, 1.0), 2)
                secondary = 0
                total = primary
                denial_status = None
                denial_reason = None
                carrier = random.choice(['M/M', 'CALOPTIMA'])

            # Filing deadline
            deadline_days = 365 if carrier == 'M/M' else 180 if carrier in ('CALOPTIMA', 'FAMILY', 'INS', 'W/C') else 90
            appeal_deadline = (svc_date + timedelta(days=deadline_days)).isoformat() if total == 0 else None

            claims.append((
                patient, doctor, scan, False, carrier, modality,
                svc_date.isoformat(), primary, secondary, total, 0,
                random.choice(DOCTORS) if random.random() > 0.5 else None,
                random.randint(10000, 99999),
                scan,
                denial_status, denial_reason, appeal_deadline,
                expected,
                'SEED_DATA',
            ))

        db.executemany("""
            INSERT INTO billing_records (
                patient_name, referring_doctor, scan_type, gado_used, insurance_carrier, modality,
                service_date, primary_payment, secondary_payment, total_payment, extra_charges,
                reading_physician, patient_id, description,
                denial_status, denial_reason_code, appeal_deadline,
                billed_amount, import_source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, claims)

        # Add a few duplicates for the duplicate detector
        for i in range(5):
            c = claims[i]
            db.execute("""
                INSERT INTO billing_records (
                    patient_name, referring_doctor, scan_type, gado_used, insurance_carrier, modality,
                    service_date, primary_payment, secondary_payment, total_payment, extra_charges,
                    reading_physician, patient_id, description,
                    denial_status, denial_reason_code, appeal_deadline,
                    billed_amount, import_source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, c)

        db.commit()
        count = db.execute("SELECT COUNT(*) FROM billing_records").fetchone()[0]
        print(f"Seeded {count} billing records, {len(PAYERS)} payers, {len(FEE_SCHEDULE)} fee schedule entries.")


if __name__ == '__main__':
    seed()
