"""Seed payer configuration and fee schedule into the database."""
from app import create_app
from app.models import db, Payer, FeeSchedule

PAYERS = [
    ('M/M', 'Medicare/Medicaid', 365, True, 0.25),
    ('CALOPTIMA', 'CalOptima Managed Medicaid', 180, True, 0.25),
    ('FAMILY', 'Family Health Plan', 180, False, 0.25),
    ('INS', 'Commercial Insurance (General)', 180, False, 0.25),
    ('VU PHAN', 'Vu Phan Physician Group', 180, False, 0.25),
    ('W/C', 'Workers Compensation', 180, False, 0.25),
    ('BEACH', 'Beach Clinical Labs', 180, False, 0.25),
    ('ONE CALL', 'One Call Care Management', 90, False, 0.50),
    ('OC ADV', 'One Call Advanced', 180, False, 0.25),
    ('SELF PAY', 'Self Pay / Uninsured', 9999, False, 0.25),
    ('SELFPAY', 'Self Pay (alternate code)', 9999, False, 0.25),
    ('STATE', 'State Programs', 365, False, 0.25),
    ('COMP', 'Complimentary / Charity', 9999, False, 0.50),
    ('X', 'Unknown / Unclassified', 180, False, 0.50),
    ('GH', 'Group Health', 180, False, 0.25),
]

FEE_SCHEDULE = [
    ('DEFAULT', 'CT', 395.00, 0.80),
    ('DEFAULT', 'HMRI', 750.00, 0.80),
    ('DEFAULT', 'PET', 2500.00, 0.80),
    ('DEFAULT', 'BONE', 1800.00, 0.80),
    ('DEFAULT', 'OPEN', 750.00, 0.80),
    ('DEFAULT', 'DX', 250.00, 0.80),
    ('JHANGIANI', 'HMRI', 950.00, 0.80),
    ('DEFAULT_PSMA', 'PET', 8046.00, 0.80),
]


def seed():
    app = create_app()
    with app.app_context():
        # Seed payers
        for code, display_name, deadline, has_secondary, threshold in PAYERS:
            existing = Payer.query.get(code)
            if not existing:
                db.session.add(Payer(
                    code=code,
                    display_name=display_name,
                    filing_deadline_days=deadline,
                    expected_has_secondary=has_secondary,
                    alert_threshold_pct=threshold,
                ))

        # Seed fee schedule
        for payer_code, modality, rate, threshold in FEE_SCHEDULE:
            existing = FeeSchedule.query.filter_by(
                payer_code=payer_code, modality=modality
            ).first()
            if not existing:
                db.session.add(FeeSchedule(
                    payer_code=payer_code,
                    modality=modality,
                    expected_rate=rate,
                    underpayment_threshold=threshold,
                ))

        db.session.commit()
        print(f'Seeded {len(PAYERS)} payers and {len(FEE_SCHEDULE)} fee schedule entries.')


if __name__ == '__main__':
    seed()
