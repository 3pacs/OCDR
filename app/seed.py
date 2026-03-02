"""Seed database with payer and fee schedule data from ocdr.config."""

from app.extensions import db
from app.models import Payer, FeeSchedule
from ocdr.config import PAYER_CONFIG, FEE_SCHEDULE, UNDERPAYMENT_THRESHOLD


def seed_if_empty():
    """Populate payers and fee_schedule tables if they are empty."""
    if Payer.query.first() is not None:
        return

    for code, cfg in PAYER_CONFIG.items():
        db.session.add(Payer(
            code=code,
            display_name=cfg['name'],
            filing_deadline_days=cfg['deadline'],
            expected_has_secondary=cfg['has_secondary'],
            alert_threshold_pct=cfg['alert_pct'],
        ))

    for (modality, payer_code), rate in FEE_SCHEDULE.items():
        db.session.add(FeeSchedule(
            payer_code=payer_code,
            modality=modality,
            expected_rate=rate,
            underpayment_threshold=UNDERPAYMENT_THRESHOLD,
        ))

    db.session.commit()
