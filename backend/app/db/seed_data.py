"""Seed data for payers and fee schedule tables."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.payer import Payer, FeeSchedule


PAYERS = [
    {"code": "M/M", "display_name": "Medicare/Medicaid", "filing_deadline_days": 365, "expected_has_secondary": True, "alert_threshold_pct": 0.25},
    {"code": "CALOPTIMA", "display_name": "CalOptima Managed Medicaid", "filing_deadline_days": 180, "expected_has_secondary": True, "alert_threshold_pct": 0.25},
    {"code": "FAMILY", "display_name": "Family Health Plan", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "INS", "display_name": "Commercial Insurance (General)", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "VU PHAN", "display_name": "Vu Phan Physician Group", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "W/C", "display_name": "Workers Compensation", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "BEACH", "display_name": "Beach Clinical Labs", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "ONE CALL", "display_name": "One Call Care Management", "filing_deadline_days": 90, "expected_has_secondary": False, "alert_threshold_pct": 0.50},
    {"code": "OC ADV", "display_name": "One Call Advanced", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "SELF PAY", "display_name": "Self Pay / Uninsured", "filing_deadline_days": 9999, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "SELFPAY", "display_name": "Self Pay (alternate code)", "filing_deadline_days": 9999, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "STATE", "display_name": "State Programs", "filing_deadline_days": 365, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "COMP", "display_name": "Complimentary / Charity", "filing_deadline_days": 9999, "expected_has_secondary": False, "alert_threshold_pct": 0.50},
    {"code": "X", "display_name": "Unknown / Unclassified", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.50},
    {"code": "GH", "display_name": "Group Health", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "JHANGIANI", "display_name": "Jhangiani Physician Group", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
]

FEE_SCHEDULES = [
    {"payer_code": "DEFAULT", "modality": "CT", "expected_rate": 395.00, "underpayment_threshold": 0.80},
    {"payer_code": "DEFAULT", "modality": "HMRI", "expected_rate": 750.00, "underpayment_threshold": 0.80},
    {"payer_code": "DEFAULT", "modality": "PET", "expected_rate": 2500.00, "underpayment_threshold": 0.80},
    {"payer_code": "DEFAULT", "modality": "BONE", "expected_rate": 1800.00, "underpayment_threshold": 0.80},
    {"payer_code": "DEFAULT", "modality": "OPEN", "expected_rate": 750.00, "underpayment_threshold": 0.80},
    {"payer_code": "DEFAULT", "modality": "DX", "expected_rate": 250.00, "underpayment_threshold": 0.80},
    {"payer_code": "JHANGIANI", "modality": "HMRI", "expected_rate": 950.00, "underpayment_threshold": 0.80},
    {"payer_code": "DEFAULT", "modality": "PET_PSMA", "expected_rate": 8046.00, "underpayment_threshold": 0.80},
]


async def seed_payers(session: AsyncSession) -> int:
    """Insert payer records if they don't already exist. Returns count inserted."""
    existing = await session.execute(select(Payer.code))
    existing_codes = {row[0] for row in existing.fetchall()}
    count = 0
    for p in PAYERS:
        if p["code"] not in existing_codes:
            session.add(Payer(**p))
            count += 1
    if count:
        await session.commit()
    return count


async def seed_fee_schedule(session: AsyncSession) -> int:
    """Insert fee schedule records if they don't already exist. Returns count inserted."""
    existing = await session.execute(select(FeeSchedule.payer_code, FeeSchedule.modality))
    existing_keys = {(row[0], row[1]) for row in existing.fetchall()}
    count = 0
    for f in FEE_SCHEDULES:
        if (f["payer_code"], f["modality"]) not in existing_keys:
            session.add(FeeSchedule(**f))
            count += 1
    if count:
        await session.commit()
    return count


async def run_all_seeds(session: AsyncSession) -> dict:
    """Run all seed operations."""
    payers_count = await seed_payers(session)
    fees_count = await seed_fee_schedule(session)
    return {"payers_inserted": payers_count, "fee_schedules_inserted": fees_count}
