"""API routes for admin operations (F-20, seed data)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db

router = APIRouter()


@router.post("/backup/run")
async def run_backup():
    """Run database backup now (F-20)."""
    from backend.app.infra.backup_manager import run_backup
    try:
        result = run_backup()
        return result
    except RuntimeError as e:
        from fastapi import HTTPException
        raise HTTPException(500, str(e))


@router.get("/backup/history")
async def backup_history():
    """List backup history (F-20)."""
    from backend.app.infra.backup_manager import get_backup_history
    return {"backups": get_backup_history()}


@router.post("/seed")
async def run_seed(db: AsyncSession = Depends(get_db)):
    """Seed payer and fee schedule data."""
    from backend.app.db.seed_data import run_all_seeds
    result = await run_all_seeds(db)
    return result


@router.get("/data-audit")
async def data_audit(db: AsyncSession = Depends(get_db)):
    """Run a full data quality audit across all billing records.

    Checks: unknown payers, unknown modalities, missing fields,
    payment anomalies, date issues, and returns actionable results.
    """
    from sqlalchemy import select, func, case, or_
    from backend.app.models.billing import BillingRecord
    from backend.app.models.payer import Payer
    from backend.app.analytics.data_validation import VALID_MODALITIES, VALID_DENIAL_STATUSES

    issues = []

    # --- 1. Unknown payers (not in payers table) ---
    known_q = select(Payer.code)
    known_payers = {r[0] for r in (await db.execute(known_q)).fetchall()}

    carrier_q = select(
        BillingRecord.insurance_carrier.label("carrier"),
        func.count().label("count"),
    ).group_by(BillingRecord.insurance_carrier)
    for r in await db.execute(carrier_q):
        if r.carrier and r.carrier not in known_payers:
            issues.append({
                "category": "UNKNOWN_PAYER",
                "severity": "HIGH" if r.count > 50 else "MEDIUM",
                "field": "insurance_carrier",
                "value": r.carrier,
                "count": r.count,
                "message": f"Payer '{r.carrier}' ({r.count} records) not in payers table — add it or fix spelling",
                "fix": f"Add to payers table with correct filing deadline, or normalize to existing code",
            })

    # --- 2. Unknown modalities ---
    mod_q = select(
        BillingRecord.modality.label("mod"),
        func.count().label("count"),
    ).group_by(BillingRecord.modality)
    for r in await db.execute(mod_q):
        if r.mod and r.mod.upper() not in VALID_MODALITIES:
            issues.append({
                "category": "UNKNOWN_MODALITY",
                "severity": "HIGH" if r.count > 20 else "MEDIUM",
                "field": "modality",
                "value": r.mod,
                "count": r.count,
                "message": f"Modality '{r.mod}' ({r.count} records) not recognized",
                "fix": f"Map to a valid modality or add to VALID_MODALITIES",
            })

    # --- 3. Negative payments ---
    neg_q = select(func.count()).where(
        or_(
            BillingRecord.primary_payment < 0,
            BillingRecord.secondary_payment < 0,
            BillingRecord.total_payment < 0,
        )
    )
    neg_count = (await db.execute(neg_q)).scalar() or 0
    if neg_count > 0:
        issues.append({
            "category": "NEGATIVE_PAYMENT",
            "severity": "HIGH",
            "field": "payment",
            "value": None,
            "count": neg_count,
            "message": f"{neg_count} records have negative payment amounts",
            "fix": "Review and correct — negative payments may indicate refunds or data errors",
        })

    # --- 4. Total != Primary + Secondary ---
    mismatch_q = select(func.count()).where(
        BillingRecord.primary_payment > 0,
        BillingRecord.total_payment > 0,
        func.abs(BillingRecord.total_payment - BillingRecord.primary_payment - BillingRecord.secondary_payment) > 1,
    )
    mismatch_count = (await db.execute(mismatch_q)).scalar() or 0
    if mismatch_count > 0:
        issues.append({
            "category": "PAYMENT_MISMATCH",
            "severity": "MEDIUM",
            "field": "total_payment",
            "value": None,
            "count": mismatch_count,
            "message": f"{mismatch_count} records where total != primary + secondary (>$1 difference)",
            "fix": "May include extra charges or manual adjustments — verify and reconcile",
        })

    # --- 5. Future service dates ---
    from datetime import date
    future_q = select(func.count()).where(BillingRecord.service_date > date.today())
    future_count = (await db.execute(future_q)).scalar() or 0
    if future_count > 0:
        issues.append({
            "category": "FUTURE_DATE",
            "severity": "HIGH",
            "field": "service_date",
            "value": None,
            "count": future_count,
            "message": f"{future_count} records have service dates in the future",
            "fix": "Likely data entry or date parsing errors — review and correct",
        })

    # --- 6. Placeholder carrier names ---
    placeholder_q = select(func.count()).where(
        BillingRecord.insurance_carrier.in_(["X", "UNKNOWN", "N/A", "NA", "NONE", ""])
    )
    placeholder_count = (await db.execute(placeholder_q)).scalar() or 0
    if placeholder_count > 0:
        issues.append({
            "category": "PLACEHOLDER_CARRIER",
            "severity": "MEDIUM",
            "field": "insurance_carrier",
            "value": None,
            "count": placeholder_count,
            "message": f"{placeholder_count} records with placeholder insurance carrier",
            "fix": "Verify actual payer from patient records and update",
        })

    # --- 7. Invalid denial statuses ---
    denial_q = select(
        BillingRecord.denial_status.label("status"),
        func.count().label("count"),
    ).where(
        BillingRecord.denial_status.isnot(None),
    ).group_by(BillingRecord.denial_status)
    for r in await db.execute(denial_q):
        if r.status.upper() not in VALID_DENIAL_STATUSES:
            issues.append({
                "category": "INVALID_DENIAL_STATUS",
                "severity": "LOW",
                "field": "denial_status",
                "value": r.status,
                "count": r.count,
                "message": f"Denial status '{r.status}' ({r.count} records) not in valid set",
                "fix": f"Map to one of: {', '.join(sorted(VALID_DENIAL_STATUSES))}",
            })

    # --- 8. Records missing service_year ---
    no_year_q = select(func.count()).where(
        or_(BillingRecord.service_year.is_(None), BillingRecord.service_year == "")
    )
    no_year = (await db.execute(no_year_q)).scalar() or 0
    total_q = select(func.count()).select_from(BillingRecord)
    total = (await db.execute(total_q)).scalar() or 0
    if no_year > 0:
        issues.append({
            "category": "MISSING_YEAR",
            "severity": "LOW",
            "field": "service_year",
            "value": None,
            "count": no_year,
            "message": f"{no_year} records missing service_year — needed for trend analysis",
            "fix": "Derive from service_date: UPDATE billing_records SET service_year = EXTRACT(YEAR FROM service_date)::text WHERE service_year IS NULL",
        })

    # Sort by severity
    sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    issues.sort(key=lambda i: sev_order.get(i["severity"], 3))

    return {
        "total_records": total,
        "issues": issues,
        "issue_count": len(issues),
        "total_affected": sum(i.get("count", 0) for i in issues),
        "data_quality_score": round(max(0, 100 - len(issues) * 5 - sum(
            i["count"] for i in issues if i["severity"] == "HIGH"
        ) / max(total, 1) * 100), 1),
    }


@router.get("/data-classification")
async def data_classification():
    """Return the data classification schema for documentation.

    Shows which fields are static, dynamic, derived, and externally validatable.
    """
    return {
        "billing_records": {
            "static_fields": {
                "description": "Set during import, should NOT change after initial load",
                "fields": [
                    "patient_name", "referring_doctor", "scan_type", "gado_used",
                    "insurance_carrier", "modality", "service_date", "patient_id",
                    "birth_date", "modality_code", "description", "service_month",
                    "service_year", "is_new_patient", "topaz_id", "import_source",
                    "reading_physician", "patient_name_display", "schedule_date",
                ],
            },
            "dynamic_fields": {
                "description": "Change through workflow (payments, denials, matching)",
                "fields": [
                    "primary_payment", "secondary_payment", "total_payment",
                    "extra_charges", "denial_status", "denial_reason_code",
                    "era_claim_id", "appeal_deadline",
                ],
            },
            "derived_fields": {
                "description": "Computed by system from other fields",
                "fields": ["is_psma"],
                "rules": {
                    "is_psma": "True if description contains 'PSMA' or (modality=PET and description contains GA-68/GALLIUM)",
                },
            },
        },
        "era_claim_lines": {
            "static_fields": {
                "description": "Parsed from 835 files — payer's authoritative payment record. NEVER modify.",
                "fields": [
                    "claim_id", "claim_status", "billed_amount", "paid_amount",
                    "patient_name_835", "service_date_835", "cpt_code",
                    "cas_group_code", "cas_reason_code", "cas_adjustment_amount",
                ],
            },
            "dynamic_fields": {
                "description": "Updated by auto-matcher only",
                "fields": ["match_confidence", "matched_billing_id"],
            },
        },
        "payers": {
            "classification": "SEMI-STATIC",
            "description": "Changes ~1-2x/year when new contracts signed",
            "externally_validatable": {
                "filing_deadline_days": "Verify against payer contract terms",
                "expected_has_secondary": "M/M and managed Medicaid plans typically have secondary",
            },
        },
        "fee_schedule": {
            "classification": "SEMI-STATIC",
            "description": "Changes annually during contract renegotiation",
            "externally_validatable": {
                "expected_rate": "Compare against CMS fee schedule and payer contract rates",
                "underpayment_threshold": "Should be 0.80 (80%) for most, higher for guaranteed-rate contracts",
            },
        },
        "valid_enums": {
            "modalities": ["CT", "HMRI", "PET", "BONE", "OPEN", "DX", "PET_PSMA", "FLUORO", "MAMMO", "US", "NM", "DEXA"],
            "denial_statuses": ["DENIED", "PENDING", "APPEALED", "OVERTURNED", "WRITTEN_OFF", "RESUBMITTED", "PAID_ON_APPEAL"],
            "claim_statuses": {"1": "PAID_PRIMARY", "2": "PAID_SECONDARY", "4": "DENIED", "22": "REVERSAL", "23": "PREDETERMINATION"},
            "cas_group_codes": {"CO": "Contractual Obligation", "CR": "Correction/Reversal", "OA": "Other Adjustment", "PI": "Payer Initiated Reduction", "PR": "Patient Responsibility"},
            "payment_methods": ["CHK", "ACH", "NON", "FWT", "BOP"],
        },
    }
