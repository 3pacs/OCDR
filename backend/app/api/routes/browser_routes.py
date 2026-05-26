"""Browser-based data validation API routes.

Endpoints for launching browser validators against external portals
(Office Ally, Purview/Candelis, bank) and comparing portal data to our DB.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db
from backend.app.models.billing import BillingRecord
from backend.app.models.era import ERAPayment, ERAClaimLine

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/status")
async def browser_status():
    """Check if browser-use is installed and configured."""
    status = {"browser_use_installed": False, "validators": {}}

    try:
        import browser_use  # noqa: F401
        status["browser_use_installed"] = True
    except ImportError:
        pass

    import os
    # Check portal credentials
    portals = {
        "payer": {
            "name": "Office Ally / Payer Portal",
            "url_env": "PAYER_PORTAL_URL",
            "user_env": "OFFICE_ALLY_USER",
            "configured": bool(os.environ.get("OFFICE_ALLY_USER")),
        },
        "pacs": {
            "name": "Purview / Candelis PACS",
            "url_env": "PACS_PORTAL_URL",
            "user_env": "PURVIEW_USER",
            "configured": bool(os.environ.get("PURVIEW_USER")),
        },
        "bank": {
            "name": "Bank Portal",
            "url_env": "BANK_PORTAL_URL",
            "user_env": "BANK_PORTAL_USER",
            "configured": bool(os.environ.get("BANK_PORTAL_USER")),
        },
    }
    status["validators"] = portals
    return status


@router.get("/records/billing")
async def get_billing_records_for_validation(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    carrier: Optional[str] = None,
    has_era_match: Optional[bool] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Get billing records formatted for browser validation."""
    query = select(BillingRecord).order_by(BillingRecord.service_date.desc())

    if carrier:
        query = query.where(BillingRecord.insurance_carrier == carrier)
    if has_era_match is True:
        query = query.where(BillingRecord.era_claim_id.isnot(None))
    elif has_era_match is False:
        query = query.where(BillingRecord.era_claim_id.is_(None))
    if date_from:
        query = query.where(BillingRecord.service_date >= date_from)
    if date_to:
        query = query.where(BillingRecord.service_date <= date_to)

    query = query.limit(limit)
    result = await db.execute(query)
    records = result.scalars().all()

    return {
        "count": len(records),
        "records": [
            {
                "record_id": str(r.id),
                "id": r.id,
                "patient_name": r.patient_name,
                "patient_name_display": r.patient_name_display,
                "patient_id": r.patient_id,
                "service_date": str(r.service_date) if r.service_date else None,
                "modality": r.modality,
                "scan_type": r.scan_type,
                "referring_doctor": r.referring_doctor,
                "insurance_carrier": r.insurance_carrier,
                "total_payment": float(r.total_payment) if r.total_payment else 0,
                "denial_status": r.denial_status,
                "denial_reason_code": r.denial_reason_code,
                "era_claim_id": r.era_claim_id,
                "topaz_id": r.topaz_id,
                "check_eft_number": None,  # Populated from ERA if matched
            }
            for r in records
        ],
    }


@router.get("/records/era")
async def get_era_records_for_validation(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    payer: Optional[str] = None,
    has_check: Optional[bool] = None,
):
    """Get ERA payment records for bank validation."""
    query = select(ERAPayment).order_by(ERAPayment.payment_date.desc())

    if payer:
        query = query.where(ERAPayment.payer_name.ilike(f"%{payer}%"))
    if has_check is True:
        query = query.where(ERAPayment.check_eft_number.isnot(None))

    query = query.limit(limit)
    result = await db.execute(query)
    payments = result.scalars().all()

    return {
        "count": len(payments),
        "records": [
            {
                "record_id": str(p.id),
                "id": p.id,
                "check_eft_number": p.check_eft_number,
                "payment_amount": float(p.payment_amount) if p.payment_amount else 0,
                "payment_date": str(p.payment_date) if p.payment_date else None,
                "payment_method": p.payment_method,
                "payer_name": p.payer_name,
                "filename": p.filename,
            }
            for p in payments
        ],
    }


@router.post("/validate/payer")
async def validate_payer_portal(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    carrier: Optional[str] = None,
    headless: bool = Query(True),
    portal_url: Optional[str] = None,
):
    """Run payer portal validation against billing records.

    Launches a browser, logs into Office Ally, and cross-checks
    claim status and payment amounts.
    """
    from backend.app.browser.payer_validator import PayerPortalValidator

    # Get records to validate
    query = select(BillingRecord).where(
        BillingRecord.era_claim_id.isnot(None)
    ).order_by(BillingRecord.service_date.desc()).limit(limit)

    if carrier:
        query = query.where(BillingRecord.insurance_carrier == carrier)

    result = await db.execute(query)
    records = result.scalars().all()

    db_records = [
        {
            "record_id": str(r.id),
            "patient_name": r.patient_name,
            "service_date": str(r.service_date) if r.service_date else "",
            "era_claim_id": r.era_claim_id,
            "total_payment": float(r.total_payment) if r.total_payment else 0,
            "denial_status": r.denial_status,
            "denial_reason_code": r.denial_reason_code,
            "insurance_carrier": r.insurance_carrier,
        }
        for r in records
    ]

    validator = PayerPortalValidator(portal_url=portal_url, headless=headless)
    return await validator.validate(db_records, max_records=limit)


@router.post("/validate/pacs")
async def validate_pacs_portal(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    headless: bool = Query(True),
    portal_url: Optional[str] = None,
):
    """Run PACS validation against billing records.

    Launches a browser, logs into Purview/Candelis, and cross-checks
    patient demographics, study dates, and modalities.
    """
    from backend.app.browser.pacs_validator import PACSValidator

    query = select(BillingRecord).order_by(
        BillingRecord.service_date.desc()
    ).limit(limit)

    result = await db.execute(query)
    records = result.scalars().all()

    db_records = [
        {
            "record_id": str(r.id),
            "patient_name": r.patient_name,
            "patient_name_display": r.patient_name_display,
            "patient_id": r.patient_id,
            "service_date": str(r.service_date) if r.service_date else "",
            "modality": r.modality,
            "scan_type": r.scan_type,
            "referring_doctor": r.referring_doctor,
        }
        for r in records
    ]

    validator = PACSValidator(portal_url=portal_url, headless=headless)
    return await validator.validate(db_records, max_records=limit)


@router.post("/validate/bank")
async def validate_bank_portal(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    headless: bool = Query(True),
    portal_url: Optional[str] = None,
):
    """Run bank validation against ERA payment records.

    Launches a browser, logs into bank portal, and cross-checks
    deposit amounts and check/EFT numbers.
    """
    from backend.app.browser.bank_validator import BankValidator

    query = select(ERAPayment).where(
        ERAPayment.check_eft_number.isnot(None)
    ).order_by(ERAPayment.payment_date.desc()).limit(limit)

    result = await db.execute(query)
    payments = result.scalars().all()

    db_records = [
        {
            "record_id": str(p.id),
            "check_eft_number": p.check_eft_number,
            "payment_amount": float(p.payment_amount) if p.payment_amount else 0,
            "payment_date": str(p.payment_date) if p.payment_date else "",
            "payment_method": p.payment_method,
            "payer_name": p.payer_name,
        }
        for p in payments
    ]

    validator = BankValidator(portal_url=portal_url, headless=headless)
    return await validator.validate(db_records, max_records=limit)


@router.post("/launch")
async def launch_manual_browser(
    portal_type: str = Query(..., regex="^(payer|pacs|bank)$"),
    portal_url: Optional[str] = None,
):
    """Launch a visible browser for manual login.

    Use when portal has CAPTCHA or 2FA. User logs in manually,
    then calls /validate/{type} with headless=false to run checks
    on the same browser session.
    """
    import os
    from backend.app.browser.base_validator import ManualBrowserSession

    urls = {
        "payer": os.environ.get("PAYER_PORTAL_URL", "https://pm.officeally.com/pm/login.aspx"),
        "pacs": os.environ.get("PACS_PORTAL_URL", "https://purview.example.com/login"),
        "bank": os.environ.get("BANK_PORTAL_URL", "https://online.bank.example.com/login"),
    }

    url = portal_url or urls.get(portal_type, "")
    session = ManualBrowserSession(url)
    return await session.launch()


@router.get("/validation-summary")
async def get_validation_summary(db: AsyncSession = Depends(get_db)):
    """Get summary statistics for validation readiness."""
    # Count records by category
    billing_count = (await db.execute(
        select(func.count()).select_from(BillingRecord)
    )).scalar() or 0

    matched_count = (await db.execute(
        select(func.count()).select_from(BillingRecord).where(
            BillingRecord.era_claim_id.isnot(None)
        )
    )).scalar() or 0

    era_count = (await db.execute(
        select(func.count()).select_from(ERAPayment)
    )).scalar() or 0

    era_with_check = (await db.execute(
        select(func.count()).select_from(ERAPayment).where(
            ERAPayment.check_eft_number.isnot(None)
        )
    )).scalar() or 0

    denied_count = (await db.execute(
        select(func.count()).select_from(BillingRecord).where(
            BillingRecord.denial_status == "DENIED"
        )
    )).scalar() or 0

    return {
        "billing_records": billing_count,
        "era_matched": matched_count,
        "era_payments": era_count,
        "era_with_check_eft": era_with_check,
        "denied_claims": denied_count,
        "ready_for_payer_validation": matched_count,
        "ready_for_pacs_validation": billing_count,
        "ready_for_bank_validation": era_with_check,
    }
