"""Seed payer configuration, fee schedule, and denial reason codes into the database."""
from app import create_app
from app.models import db, Payer, FeeSchedule, DenialReasonCode

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
    ('JHANGIANI', 'Jhangiani Physician Group', 180, False, 0.25),
    ('GH', 'Group Health', 180, False, 0.25),
]

DENIAL_REASON_CODES = [
    ('CO', '4', 'The procedure code is inconsistent with the modifier used or a required modifier is missing', 'AUTH_ISSUE'),
    ('CO', '16', 'Claim/service lacks information needed for adjudication', 'FRONT_DESK'),
    ('CO', '45', 'Charge exceeds fee schedule/maximum allowable', 'CONTRACT'),
    ('CO', '50', 'These are non-covered services because this is not deemed a medical necessity', 'AUTH_ISSUE'),
    ('CO', '97', 'The benefit for this service is included in the payment/allowance for another service', 'CODING'),
    ('PR', '1', 'Deductible amount', 'PATIENT_RESP'),
    ('PR', '2', 'Coinsurance amount', 'PATIENT_RESP'),
    ('PR', '3', 'Co-payment amount', 'PATIENT_RESP'),
    ('OA', '23', 'The impact of prior payer(s) adjudication including payments and/or adjustments', 'CONTRACT'),
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

        # Seed denial reason codes
        for group, reason, desc, category in DENIAL_REASON_CODES:
            existing = DenialReasonCode.query.filter_by(
                group_code=group, reason_code=reason
            ).first()
            if not existing:
                db.session.add(DenialReasonCode(
                    group_code=group,
                    reason_code=reason,
                    description=desc,
                    category=category,
                ))

        db.session.commit()
        print(f'Seeded {len(PAYERS)} payers, {len(FEE_SCHEDULE)} fee schedule entries, '
              f'and {len(DENIAL_REASON_CODES)} denial reason codes.')


if __name__ == '__main__':
    seed()
