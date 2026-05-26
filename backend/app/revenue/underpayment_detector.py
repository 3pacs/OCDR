"""
Underpayment Detector (F-05) — CPT-based rewrite.

Compares actual payment against expected rate from fee_schedule.
Primary lookup: CPT code + carrier (what insurers actually reimburse against).
Fallback: modality + carrier (legacy, for records without CPT codes).
Handles: gado/contrast premiums, PSMA, charge categories, per-carrier thresholds.

Rate lookup priority:
  1. (payer, cpt_code) — CPT-specific payer rate (min 3 samples)
  2. (DEFAULT, cpt_code) — CPT-specific default rate (min 3 samples)
  3. (payer, modality, charge_category) — modality-level payer rate
  4. (payer, modality, STANDARD) — modality-level without category
  5. (DEFAULT, modality, STANDARD) — global modality default

Billing cycle exclusion:
  Claims within the last 30 days are in the "active billing cycle" —
  they haven't had time to be paid yet and should NOT be flagged as
  underpaid. This prevents false positives on recent scans.

COMP carrier exclusion:
  Complimentary scans (carrier=COMP) have $0 expected payment and
  are excluded from underpayment detection entirely.

Implements BR-03 (gado premium) and BR-02 (PSMA rate).
"""

import logging
from datetime import date, timedelta

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord
from backend.app.models.era import ERAClaimLine, ERAPayment
from backend.app.models.payer import FeeSchedule
from backend.app.revenue.writeoff_filter import not_written_off, COMP_CARRIERS

logger = logging.getLogger(__name__)

GADO_PREMIUM = 200.00  # BR-03
BILLING_CYCLE_DAYS = 30  # Claims within this window are still in active billing


# ── Payment method normalization ──────────────────────────────────

PAYMENT_METHOD_MAP = {
    # ERA 835 BPR codes -> normalized
    "CHK": "CHECK",
    "ACH": "EFT",
    "FWT": "WIRE",
    "NON": "NON_PAYMENT",
    # Common variations
    "CHECK": "CHECK",
    "EFT": "EFT",
    "WIRE": "WIRE",
    "CREDIT_CARD": "CREDIT_CARD",
    "CC": "CREDIT_CARD",
    "CASH": "CASH",
    "ELECTRONIC": "EFT",
}


def normalize_payment_method(raw_method: str | None) -> str | None:
    """Normalize payment method codes to standard values."""
    if not raw_method:
        return None
    return PAYMENT_METHOD_MAP.get(raw_method.upper().strip(), raw_method.upper().strip())


# ── Charge category inference ─────────────────────────────────────

def infer_charge_category(record: BillingRecord) -> str:
    """Infer charge category from billing record fields.

    Returns: WITH_CONTRAST, WITHOUT_CONTRAST, PSMA, or STANDARD
    """
    if record.charge_category:
        return record.charge_category

    if record.is_psma and record.modality == "PET":
        return "PSMA"

    if record.gado_used and record.modality in ("HMRI", "OPEN", "MR"):
        return "WITH_CONTRAST"

    return "STANDARD"


# ── Fee schedule loading ──────────────────────────────────────────

def _build_fee_lookups(fees: list) -> tuple[dict, dict]:
    """Build comprehensive fee lookup maps from fee_schedule entries.

    Returns:
        cpt_map: {(payer_code, cpt_code): {rate, thresh, sample_count, modality}}
        modality_map: {(payer_code, modality, category): {rate, thresh, gado_premium}}
    """
    cpt_map: dict[tuple, dict] = {}
    modality_map: dict[tuple, dict] = {}

    for f in fees:
        rate = float(f.expected_rate)
        thresh = float(f.underpayment_threshold)
        cpt = f.cpt_code
        category = getattr(f, "charge_category", None) or "STANDARD"
        sample_count = getattr(f, "sample_count", 0) or 0

        if cpt:
            key = (f.payer_code, cpt)
            existing = cpt_map.get(key)
            # Prefer entry with more samples
            if not existing or sample_count > existing.get("sample_count", 0):
                cpt_map[key] = {
                    "expected_rate": rate,
                    "threshold": thresh,
                    "sample_count": sample_count,
                    "modality": f.modality,
                }
        else:
            key = (f.payer_code, f.modality, category)
            modality_map[key] = {
                "expected_rate": rate,
                "threshold": thresh,
                "gado_premium": float(getattr(f, "gado_premium", 0) or 0),
            }
            # Also store as STANDARD for fallback
            base_key = (f.payer_code, f.modality, "STANDARD")
            if base_key not in modality_map:
                modality_map[base_key] = modality_map[key]

    return cpt_map, modality_map


def _lookup_expected_rate(
    carrier: str,
    modality: str,
    cpt_code: str | None,
    charge_category: str,
    cpt_map: dict,
    modality_map: dict,
    threshold_override: float | None = None,
) -> tuple[float, float, str] | None:
    """Look up expected rate using CPT-first fallback chain.

    Returns (expected_rate, threshold, lookup_method) or None if no schedule found.
    """
    # ── CPT-based lookup (preferred) ──────────────────────────────
    cpt_rate = None
    cpt_threshold = None
    if cpt_code:
        # 1a. Exact: carrier + CPT
        entry = cpt_map.get((carrier, cpt_code))
        if entry and entry["sample_count"] >= 3:
            rate = entry["expected_rate"]
            thresh = threshold_override or entry["threshold"]
            return rate, thresh, "cpt"

        # 1b. Default CPT rate
        entry = cpt_map.get(("DEFAULT", cpt_code))
        if entry and entry["sample_count"] >= 3:
            rate = entry["expected_rate"]
            thresh = threshold_override or entry["threshold"]
            return rate, thresh, "cpt"

        # 1c. Low sample count — save for later fallback
        entry = cpt_map.get((carrier, cpt_code)) or cpt_map.get(("DEFAULT", cpt_code))
        if entry:
            cpt_rate = entry["expected_rate"]
            cpt_threshold = entry["threshold"]

    # ── Modality-based lookup (fallback) ──────────────────────────
    entry = modality_map.get((carrier, modality, charge_category))

    if not entry and charge_category != "STANDARD":
        entry = modality_map.get((carrier, modality, "STANDARD"))

    # PSMA default
    if not entry and charge_category == "PSMA" and modality == "PET":
        entry = modality_map.get(("DEFAULT_PSMA", "PET", "PSMA"))
        if not entry:
            entry = modality_map.get(("DEFAULT_PSMA", "PET", "STANDARD"))

    # Global default for modality
    if not entry:
        entry = modality_map.get(("DEFAULT", modality, charge_category))
    if not entry:
        entry = modality_map.get(("DEFAULT", modality, "STANDARD"))

    if entry:
        expected = entry["expected_rate"]
        thresh = threshold_override or entry["threshold"]

        # Apply gado premium for contrast studies
        if charge_category == "WITH_CONTRAST":
            gado_premium = entry.get("gado_premium", 0.0)
            expected += gado_premium if gado_premium > 0 else 200.0

        # If we had a CPT rate, prefer it (more specific)
        if cpt_rate is not None:
            return cpt_rate, threshold_override or cpt_threshold, "cpt"
        return expected, thresh, "modality"

    # No modality match — use CPT rate if we had one
    if cpt_rate is not None:
        return cpt_rate, threshold_override or cpt_threshold, "cpt"

    return None


def get_actual_payment(record: BillingRecord) -> float:
    """Get the best available actual payment amount for a billing record.

    Priority: era_paid_amount (from matched 835) > total_payment (from billing import)
    """
    if record.era_paid_amount is not None:
        return float(record.era_paid_amount)
    return float(record.total_payment or 0)


async def _get_cpt_for_billing(session: AsyncSession, billing_ids: list[int]) -> dict[int, str]:
    """Get CPT codes from matched ERA claims for billing records."""
    if not billing_ids:
        return {}
    result = await session.execute(
        select(ERAClaimLine.matched_billing_id, ERAClaimLine.cpt_code).where(
            ERAClaimLine.matched_billing_id.in_(billing_ids),
            ERAClaimLine.cpt_code.isnot(None),
        )
    )
    cpt_map: dict[int, str] = {}
    for billing_id, cpt in result.all():
        if billing_id not in cpt_map:  # First (primary) claim wins
            cpt_map[billing_id] = cpt
    return cpt_map


def _check_underpayment(record: BillingRecord, cpt_code: str | None,
                        cpt_map: dict, modality_map: dict,
                        threshold_override: float | None = None) -> dict | None:
    """Check if a single billing record is underpaid.

    Returns dict with underpayment details, or None if not underpaid.
    """
    # Skip COMP carriers — complimentary scans have $0 expected
    if record.insurance_carrier in COMP_CARRIERS:
        return None

    actual = get_actual_payment(record)
    if actual <= 0:
        return None  # unpaid — not an underpayment, it's a denial

    charge_cat = infer_charge_category(record)
    cpt = cpt_code or record.cpt_code

    rate_result = _lookup_expected_rate(
        record.insurance_carrier, record.modality, cpt, charge_cat,
        cpt_map, modality_map, threshold_override,
    )
    if rate_result is None:
        return None

    expected, thresh, method = rate_result
    if expected <= 0:
        return None

    if actual < (expected * thresh):
        variance = actual - expected
        return {
            "expected_rate": round(expected, 2),
            "variance": round(variance, 2),
            "pct_of_expected": round(actual / expected * 100, 1) if expected else 0,
            "charge_category": charge_cat,
            "threshold_used": thresh,
            "actual_payment": round(actual, 2),
            "cpt_code": cpt,
            "lookup_method": method,
        }
    return None


async def get_underpayments(
    session: AsyncSession,
    carrier: str | None = None,
    modality: str | None = None,
    threshold_override: float | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """
    Find underpaid claims by comparing to fee schedule.

    Excludes claims from the last 30 days (active billing cycle).
    Excludes COMP carrier claims (complimentary, $0 expected).
    Uses CPT-granular rates when available, falls back to modality-level.
    """
    cutoff_date = date.today() - timedelta(days=BILLING_CYCLE_DAYS)

    # Get paid claims outside active billing cycle, excluding COMP
    query = select(BillingRecord).where(
        BillingRecord.total_payment > 0,
        BillingRecord.service_date <= cutoff_date,
        ~BillingRecord.insurance_carrier.in_(COMP_CARRIERS),
        not_written_off(),
    )

    if carrier:
        query = query.where(BillingRecord.insurance_carrier == carrier)
    if modality:
        query = query.where(BillingRecord.modality == modality)

    query = query.order_by(BillingRecord.service_date.desc())

    # Get total count
    count_q = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_q)
    total_paid = total_result.scalar()

    # Get paginated results
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await session.execute(query)
    records = result.scalars().all()

    # Load fee schedule
    fee_result = await session.execute(select(FeeSchedule))
    fees = fee_result.scalars().all()
    cpt_map, modality_map = _build_fee_lookups(fees)

    # Get CPT codes from matched ERA claims
    billing_ids = [rec.id for rec in records]
    era_cpt_map = await _get_cpt_for_billing(session, billing_ids)

    underpaid = []
    for rec in records:
        cpt_code = era_cpt_map.get(rec.id)
        underpay = _check_underpayment(rec, cpt_code, cpt_map, modality_map, threshold_override)
        if underpay is None:
            continue

        underpaid.append({
            "id": rec.id,
            "patient_name": rec.patient_name,
            "service_date": rec.service_date.isoformat(),
            "modality": rec.modality,
            "cpt_code": underpay["cpt_code"],
            "insurance_carrier": rec.insurance_carrier,
            "total_payment": float(rec.total_payment or 0),
            "era_paid_amount": float(rec.era_paid_amount) if rec.era_paid_amount else None,
            "expected_rate": underpay["expected_rate"],
            "variance": underpay["variance"],
            "variance_pct": underpay["pct_of_expected"],
            "charge_category": underpay["charge_category"],
            "lookup_method": underpay["lookup_method"],
            "gado_used": rec.gado_used,
            "is_psma": rec.is_psma,
        })

    return {
        "underpaid_claims": underpaid,
        "total_paid_claims": total_paid,
        "billing_cycle_excluded_days": BILLING_CYCLE_DAYS,
        "cutoff_date": cutoff_date.isoformat(),
        "page": page,
        "per_page": per_page,
    }


async def get_underpayment_summary(session: AsyncSession) -> dict:
    """
    Summary statistics for underpayments across all paid claims.

    Excludes claims from the last 30 days (active billing cycle).
    Excludes COMP carrier claims (complimentary, $0 expected).
    """
    cutoff_date = date.today() - timedelta(days=BILLING_CYCLE_DAYS)

    result = await session.execute(
        select(BillingRecord).where(
            BillingRecord.total_payment > 0,
            BillingRecord.service_date <= cutoff_date,
            ~BillingRecord.insurance_carrier.in_(COMP_CARRIERS),
            not_written_off(),
        )
    )
    records = result.scalars().all()

    # Load fee schedule
    fee_result = await session.execute(select(FeeSchedule))
    fees = fee_result.scalars().all()
    cpt_map, modality_map = _build_fee_lookups(fees)

    # Get CPT codes for all records
    billing_ids = [rec.id for rec in records]
    era_cpt_map = await _get_cpt_for_billing(session, billing_ids)

    total_flagged = 0
    total_variance = 0.0
    by_carrier: dict[str, dict] = {}
    by_modality: dict[str, dict] = {}
    by_charge_category: dict[str, dict] = {}
    by_cpt: dict[str, dict] = {}
    by_lookup_method: dict[str, int] = {"cpt": 0, "modality": 0}

    for rec in records:
        cpt_code = era_cpt_map.get(rec.id)
        underpay = _check_underpayment(rec, cpt_code, cpt_map, modality_map)
        if underpay is None:
            continue

        total_flagged += 1
        variance = underpay["variance"]
        total_variance += variance
        charge_cat = underpay["charge_category"]
        method = underpay["lookup_method"]
        by_lookup_method[method] = by_lookup_method.get(method, 0) + 1

        # By carrier
        c = rec.insurance_carrier
        if c not in by_carrier:
            by_carrier[c] = {"count": 0, "variance": 0.0}
        by_carrier[c]["count"] += 1
        by_carrier[c]["variance"] += variance

        # By modality
        m = rec.modality
        if m not in by_modality:
            by_modality[m] = {"count": 0, "variance": 0.0}
        by_modality[m]["count"] += 1
        by_modality[m]["variance"] += variance

        # By charge category
        if charge_cat not in by_charge_category:
            by_charge_category[charge_cat] = {"count": 0, "variance": 0.0}
        by_charge_category[charge_cat]["count"] += 1
        by_charge_category[charge_cat]["variance"] += variance

        # By CPT code
        cpt = underpay.get("cpt_code")
        if cpt:
            if cpt not in by_cpt:
                by_cpt[cpt] = {"count": 0, "variance": 0.0}
            by_cpt[cpt]["count"] += 1
            by_cpt[cpt]["variance"] += variance

    # Round variances
    for v in by_carrier.values():
        v["variance"] = round(v["variance"], 2)
    for v in by_modality.values():
        v["variance"] = round(v["variance"], 2)
    for v in by_charge_category.values():
        v["variance"] = round(v["variance"], 2)
    for v in by_cpt.values():
        v["variance"] = round(v["variance"], 2)

    return {
        "total_flagged": total_flagged,
        "total_paid_claims": len(records),
        "flagged_pct": round(total_flagged / len(records) * 100, 1) if records else 0,
        "total_variance": round(total_variance, 2),
        "billing_cycle_excluded_days": BILLING_CYCLE_DAYS,
        "cutoff_date": cutoff_date.isoformat(),
        "lookup_methods": by_lookup_method,
        "by_carrier": [
            {"carrier": k, "count": v["count"], "variance": v["variance"]}
            for k, v in sorted(by_carrier.items(), key=lambda x: x[1]["variance"])
        ],
        "by_modality": [
            {"modality": k, "count": v["count"], "variance": v["variance"]}
            for k, v in sorted(by_modality.items(), key=lambda x: x[1]["variance"])
        ],
        "by_charge_category": [
            {"category": k, "count": v["count"], "variance": v["variance"]}
            for k, v in sorted(by_charge_category.items(), key=lambda x: x[1]["variance"])
        ],
        "by_cpt": [
            {"cpt_code": k, "count": v["count"], "variance": v["variance"]}
            for k, v in sorted(by_cpt.items(), key=lambda x: x[1]["variance"])[:20]
        ],
    }


# ── CPT Fee Schedule Builder ─────────────────────────────────────

from backend.app.revenue.carrier_normalization import normalize_era_payer

# CPT code prefix -> modality mapping
_CPT_MODALITY = {
    "700": "CT", "701": "CT", "702": "CT", "703": "CT", "704": "CT",
    "712": "CT", "713": "CT", "741": "CT", "742": "CT",
    "705": "HMRI", "706": "HMRI", "707": "HMRI",
    "721": "HMRI", "722": "HMRI", "723": "HMRI", "737": "HMRI",
    "788": "PET", "783": "PET",
    "782": "BONE", "780": "BONE",
    "710": "DX", "711": "DX", "730": "DX", "731": "DX",
    "A95": None, "Q99": None,
}


def _cpt_to_modality(cpt_code: str | None) -> str | None:
    """Infer modality from CPT code prefix."""
    if not cpt_code:
        return None
    primary = cpt_code.split(",")[0].strip()
    prefix = primary[:3]
    return _CPT_MODALITY.get(prefix)


async def build_cpt_fee_schedule_from_era(session: AsyncSession) -> int:
    """Analyze ERA payment history and build/update CPT-level fee schedule entries.

    Groups ERA claim line payments by (normalized carrier, CPT code) and computes
    weighted average expected rate. Only creates entries with >= 3 samples for reliability.

    Returns count of entries created/updated.
    """
    # Get payment stats by CPT + payer (raw), then normalize carrier in Python
    rows_result = await session.execute(text("""
        SELECT
            ep.payer_name,
            ecl.cpt_code,
            COUNT(*) as cnt,
            SUM(ecl.paid_amount) as total_paid
        FROM era_claim_lines ecl
        JOIN era_payments ep ON ecl.era_payment_id = ep.id
        WHERE ecl.cpt_code IS NOT NULL AND ecl.cpt_code != ''
          AND ecl.paid_amount > 0
        GROUP BY ep.payer_name, ecl.cpt_code
    """))
    rows = rows_result.fetchall()

    # Aggregate by (normalized_carrier, cpt) since multiple payer names
    # can map to the same carrier code
    aggregated: dict[tuple[str, str], dict] = {}
    for payer_name, cpt, cnt, total_paid in rows:
        carrier = normalize_era_payer(payer_name)
        if carrier == "UNKNOWN":
            continue
        key = (carrier, cpt)
        if key not in aggregated:
            aggregated[key] = {"cnt": 0, "total_paid": 0.0}
        aggregated[key]["cnt"] += cnt
        aggregated[key]["total_paid"] += float(total_paid)

    count = 0
    for (carrier, cpt), stats in aggregated.items():
        if stats["cnt"] < 3:
            continue

        modality = _cpt_to_modality(cpt)
        expected = round(stats["total_paid"] / stats["cnt"], 2)

        mod = modality or "UNKNOWN"

        # Look for existing entry matching the unique constraint
        existing_result = await session.execute(
            select(FeeSchedule).where(
                FeeSchedule.payer_code == carrier,
                FeeSchedule.modality == mod,
                FeeSchedule.cpt_code == cpt,
            )
        )
        existing = existing_result.scalars().first()

        if existing:
            existing.expected_rate = expected
            existing.sample_count = stats["cnt"]
            existing.source = "ERA_DERIVED"
        else:
            fs = FeeSchedule(
                payer_code=carrier,
                modality=mod,
                cpt_code=cpt,
                expected_rate=expected,
                underpayment_threshold=0.80,
                source="ERA_DERIVED",
                sample_count=stats["cnt"],
            )
            session.add(fs)
        count += 1

    # Also build DEFAULT rates by CPT (across all carriers)
    default_result = await session.execute(text("""
        SELECT
            ecl.cpt_code,
            COUNT(*) as cnt,
            AVG(ecl.paid_amount) as avg_paid
        FROM era_claim_lines ecl
        WHERE ecl.cpt_code IS NOT NULL AND ecl.cpt_code != ''
          AND ecl.paid_amount > 0
        GROUP BY ecl.cpt_code
        HAVING COUNT(*) >= 5
    """))
    default_rows = default_result.fetchall()

    for row in default_rows:
        cpt, cnt, avg_paid = row
        modality = _cpt_to_modality(cpt)
        mod = modality or "UNKNOWN"
        expected = round(float(avg_paid), 2)

        existing_result = await session.execute(
            select(FeeSchedule).where(
                FeeSchedule.payer_code == "DEFAULT",
                FeeSchedule.modality == mod,
                FeeSchedule.cpt_code == cpt,
            )
        )
        existing = existing_result.scalars().first()

        if existing:
            existing.expected_rate = expected
            existing.sample_count = cnt
            existing.source = "ERA_DERIVED"
        else:
            fs = FeeSchedule(
                payer_code="DEFAULT",
                modality=mod,
                cpt_code=cpt,
                expected_rate=expected,
                underpayment_threshold=0.80,
                source="ERA_DERIVED",
                sample_count=cnt,
            )
            session.add(fs)
        count += 1

    if count > 0:
        await session.commit()

    return count
