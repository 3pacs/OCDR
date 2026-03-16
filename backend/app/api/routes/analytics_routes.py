"""API routes for analytics dashboards (F-08, F-09, F-13, F-14, F-15, F-16).

Covers: Payer Monitor, Physician Analytics, PSMA Tracking, Gado Analytics,
Duplicate Detection, and Denial Reason Analytics.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, case, extract, text, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db
from backend.app.models.billing import BillingRecord
from backend.app.models.payer import Payer, FeeSchedule
from backend.app.models.era import ERAClaimLine

router = APIRouter()


# ---------------------------------------------------------------------------
# F-09: Payer Contract Monitor & Alerts
# ---------------------------------------------------------------------------

@router.get("/payer-alerts")
async def payer_alerts(db: AsyncSession = Depends(get_db)):
    """Active payer alerts — carriers with significant revenue or volume drops."""
    # Monthly revenue + volume by carrier for the last 12 months
    twelve_months_ago = date.today() - timedelta(days=365)
    result = await db.execute(
        select(
            BillingRecord.insurance_carrier,
            func.to_char(BillingRecord.service_date, 'YYYY-MM').label("month"),
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.count(BillingRecord.id).label("volume"),
        )
        .where(BillingRecord.service_date >= twelve_months_ago)
        .group_by(BillingRecord.insurance_carrier, text("2"))
        .order_by(BillingRecord.insurance_carrier, text("2"))
    )
    rows = result.all()

    # Build per-carrier monthly data
    carrier_months: dict[str, list[dict]] = {}
    for carrier, month, revenue, volume in rows:
        carrier_months.setdefault(carrier, []).append({
            "month": month,
            "revenue": float(revenue or 0),
            "volume": volume,
        })

    # Get payer thresholds
    payer_result = await db.execute(select(Payer.code, Payer.alert_threshold_pct, Payer.display_name))
    payer_map = {r.code: {"threshold": float(r.alert_threshold_pct or 0.25), "name": r.display_name} for r in payer_result.all()}

    alerts = []
    for carrier, months in carrier_months.items():
        if len(months) < 2:
            continue
        # Last month vs avg of prior 3
        sorted_months = sorted(months, key=lambda x: x["month"])
        current = sorted_months[-1]
        prior = sorted_months[-4:-1] if len(sorted_months) >= 4 else sorted_months[:-1]
        if not prior:
            continue
        avg_revenue = sum(m["revenue"] for m in prior) / len(prior)
        avg_volume = sum(m["volume"] for m in prior) / len(prior)

        threshold = payer_map.get(carrier, {}).get("threshold", 0.25)

        rev_drop = (avg_revenue - current["revenue"]) / avg_revenue if avg_revenue > 0 else 0
        vol_drop = (avg_volume - current["volume"]) / avg_volume if avg_volume > 0 else 0

        if rev_drop > threshold or vol_drop > threshold:
            severity = "RED" if rev_drop > 0.5 or vol_drop > 0.5 else "YELLOW"
            alerts.append({
                "carrier": carrier,
                "display_name": payer_map.get(carrier, {}).get("name", carrier),
                "severity": severity,
                "current_month": current["month"],
                "current_revenue": current["revenue"],
                "avg_prior_revenue": round(avg_revenue, 2),
                "revenue_drop_pct": round(rev_drop * 100, 1),
                "current_volume": current["volume"],
                "avg_prior_volume": round(avg_volume, 1),
                "volume_drop_pct": round(vol_drop * 100, 1),
            })

    alerts.sort(key=lambda x: x["revenue_drop_pct"], reverse=True)
    return {"alerts": alerts, "total": len(alerts)}


@router.get("/payer-monitor")
async def payer_monitor(db: AsyncSession = Depends(get_db)):
    """Overview of all payers with revenue trends."""
    result = await db.execute(
        select(
            BillingRecord.insurance_carrier,
            func.sum(BillingRecord.total_payment).label("total_revenue"),
            func.count(BillingRecord.id).label("total_claims"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
            func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("zero_pay_count"),
        )
        .group_by(BillingRecord.insurance_carrier)
        .order_by(func.sum(BillingRecord.total_payment).desc())
    )
    carriers = []
    for row in result.all():
        carriers.append({
            "carrier": row.insurance_carrier,
            "total_revenue": float(row.total_revenue or 0),
            "total_claims": row.total_claims,
            "avg_payment": round(float(row.avg_payment or 0), 2),
            "zero_pay_count": row.zero_pay_count,
            "zero_pay_pct": round(row.zero_pay_count / row.total_claims * 100, 1) if row.total_claims > 0 else 0,
        })
    return {"carriers": carriers}


@router.get("/payer-monitor/{carrier}")
async def payer_detail(carrier: str, db: AsyncSession = Depends(get_db)):
    """Monthly breakdown for a specific carrier."""
    result = await db.execute(
        select(
            func.to_char(BillingRecord.service_date, 'YYYY-MM').label("month"),
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.count(BillingRecord.id).label("volume"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
        )
        .where(BillingRecord.insurance_carrier == carrier)
        .group_by(text("1"))
        .order_by(text("1"))
    )
    monthly = [
        {
            "month": r.month,
            "revenue": float(r.revenue or 0),
            "volume": r.volume,
            "avg_payment": round(float(r.avg_payment or 0), 2),
        }
        for r in result.all()
    ]

    # Modality breakdown
    mod_result = await db.execute(
        select(
            BillingRecord.modality,
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.count(BillingRecord.id).label("volume"),
        )
        .where(BillingRecord.insurance_carrier == carrier)
        .group_by(BillingRecord.modality)
        .order_by(func.sum(BillingRecord.total_payment).desc())
    )
    by_modality = [
        {"modality": r.modality, "revenue": float(r.revenue or 0), "volume": r.volume}
        for r in mod_result.all()
    ]

    return {"carrier": carrier, "monthly": monthly, "by_modality": by_modality}


# ---------------------------------------------------------------------------
# F-15: Physician Analytics
# ---------------------------------------------------------------------------

@router.get("/physicians")
async def physician_rankings(
    sort_by: str = Query("revenue", enum=["revenue", "volume"]),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Top physicians ranked by revenue or volume."""
    order = func.sum(BillingRecord.total_payment).desc() if sort_by == "revenue" else func.count(BillingRecord.id).desc()
    result = await db.execute(
        select(
            BillingRecord.referring_doctor,
            func.sum(BillingRecord.total_payment).label("total_revenue"),
            func.count(BillingRecord.id).label("total_claims"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
            func.count(func.distinct(BillingRecord.insurance_carrier)).label("carrier_count"),
            func.count(func.distinct(BillingRecord.modality)).label("modality_count"),
        )
        .group_by(BillingRecord.referring_doctor)
        .order_by(order)
        .limit(limit)
    )
    physicians = []
    for r in result.all():
        physicians.append({
            "name": r.referring_doctor,
            "total_revenue": float(r.total_revenue or 0),
            "total_claims": r.total_claims,
            "avg_payment": round(float(r.avg_payment or 0), 2),
            "carrier_count": r.carrier_count,
            "modality_count": r.modality_count,
        })

    # Calculate share percentages
    total_rev = sum(p["total_revenue"] for p in physicians)
    for p in physicians:
        p["revenue_share_pct"] = round(p["total_revenue"] / total_rev * 100, 1) if total_rev > 0 else 0

    return {"physicians": physicians, "total_revenue": total_rev}


@router.get("/physicians/{name}")
async def physician_detail(name: str, db: AsyncSession = Depends(get_db)):
    """Detailed breakdown for a specific physician."""
    # By modality
    mod_result = await db.execute(
        select(
            BillingRecord.modality,
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.count(BillingRecord.id).label("volume"),
        )
        .where(BillingRecord.referring_doctor == name)
        .group_by(BillingRecord.modality)
        .order_by(func.sum(BillingRecord.total_payment).desc())
    )
    by_modality = [
        {"modality": r.modality, "revenue": float(r.revenue or 0), "volume": r.volume}
        for r in mod_result.all()
    ]

    # By carrier
    carrier_result = await db.execute(
        select(
            BillingRecord.insurance_carrier,
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.count(BillingRecord.id).label("volume"),
        )
        .where(BillingRecord.referring_doctor == name)
        .group_by(BillingRecord.insurance_carrier)
        .order_by(func.sum(BillingRecord.total_payment).desc())
    )
    by_carrier = [
        {"carrier": r.insurance_carrier, "revenue": float(r.revenue or 0), "volume": r.volume}
        for r in carrier_result.all()
    ]

    # Monthly trend
    monthly_result = await db.execute(
        select(
            func.to_char(BillingRecord.service_date, 'YYYY-MM').label("month"),
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.count(BillingRecord.id).label("volume"),
        )
        .where(BillingRecord.referring_doctor == name)
        .group_by(text("1"))
        .order_by(text("1"))
    )
    monthly = [
        {"month": r.month, "revenue": float(r.revenue or 0), "volume": r.volume}
        for r in monthly_result.all()
    ]

    # Gado usage
    gado_result = await db.execute(
        select(
            func.count(BillingRecord.id).label("total"),
            func.sum(case((BillingRecord.gado_used.is_(True), 1), else_=0)).label("gado_count"),
        )
        .where(BillingRecord.referring_doctor == name)
    )
    gado = gado_result.one()

    return {
        "name": name,
        "by_modality": by_modality,
        "by_carrier": by_carrier,
        "monthly": monthly,
        "total_claims": gado.total,
        "gado_claims": gado.gado_count,
        "gado_pct": round(gado.gado_count / gado.total * 100, 1) if gado.total > 0 else 0,
    }


# ---------------------------------------------------------------------------
# F-13: PSMA PET Tracking
# ---------------------------------------------------------------------------

@router.get("/psma")
async def psma_dashboard(db: AsyncSession = Depends(get_db)):
    """PSMA PET scan tracking — volume, revenue, trends."""
    # Overall PSMA stats
    result = await db.execute(
        select(
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
        )
        .where(BillingRecord.is_psma.is_(True))
    )
    stats = result.one()

    # Standard PET comparison
    std_result = await db.execute(
        select(
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
        )
        .where(BillingRecord.modality == "PET")
        .where(BillingRecord.is_psma.is_(False))
    )
    std_stats = std_result.one()

    # By year
    yearly = await db.execute(
        select(
            BillingRecord.service_year,
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .where(BillingRecord.is_psma.is_(True))
        .group_by(BillingRecord.service_year)
        .order_by(BillingRecord.service_year)
    )
    by_year = [
        {"year": r.service_year, "count": r.count, "revenue": float(r.revenue or 0)}
        for r in yearly.all()
    ]

    # By referring doctor
    by_doc = await db.execute(
        select(
            BillingRecord.referring_doctor,
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .where(BillingRecord.is_psma.is_(True))
        .group_by(BillingRecord.referring_doctor)
        .order_by(func.sum(BillingRecord.total_payment).desc())
        .limit(10)
    )
    by_physician = [
        {"name": r.referring_doctor, "count": r.count, "revenue": float(r.revenue or 0)}
        for r in by_doc.all()
    ]

    return {
        "psma": {
            "count": stats.count,
            "revenue": float(stats.revenue or 0),
            "avg_payment": round(float(stats.avg_payment or 0), 2),
        },
        "standard_pet": {
            "count": std_stats.count,
            "revenue": float(std_stats.revenue or 0),
            "avg_payment": round(float(std_stats.avg_payment or 0), 2),
        },
        "by_year": by_year,
        "by_physician": by_physician,
    }


# ---------------------------------------------------------------------------
# F-14: Gado Contrast Analytics
# ---------------------------------------------------------------------------

@router.get("/gado")
async def gado_dashboard(
    gado_cost_per_dose: float = Query(50.0, description="Cost per Gado dose"),
    db: AsyncSession = Depends(get_db),
):
    """Gadolinium contrast analytics — volume, revenue, margin."""
    # Overall gado stats
    result = await db.execute(
        select(
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
        )
        .where(BillingRecord.gado_used.is_(True))
    )
    stats = result.one()

    total_cost = stats.count * gado_cost_per_dose
    margin = float(stats.revenue or 0) - total_cost

    # By modality
    by_mod = await db.execute(
        select(
            BillingRecord.modality,
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .where(BillingRecord.gado_used.is_(True))
        .group_by(BillingRecord.modality)
        .order_by(func.sum(BillingRecord.total_payment).desc())
    )
    by_modality = [
        {"modality": r.modality, "count": r.count, "revenue": float(r.revenue or 0)}
        for r in by_mod.all()
    ]

    # By year
    by_yr = await db.execute(
        select(
            BillingRecord.service_year,
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .where(BillingRecord.gado_used.is_(True))
        .group_by(BillingRecord.service_year)
        .order_by(BillingRecord.service_year)
    )
    by_year = [
        {"year": r.service_year, "count": r.count, "revenue": float(r.revenue or 0)}
        for r in by_yr.all()
    ]

    # Top referring doctors for gado
    by_doc = await db.execute(
        select(
            BillingRecord.referring_doctor,
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .where(BillingRecord.gado_used.is_(True))
        .group_by(BillingRecord.referring_doctor)
        .order_by(func.count(BillingRecord.id).desc())
        .limit(10)
    )
    by_physician = [
        {"name": r.referring_doctor, "count": r.count, "revenue": float(r.revenue or 0)}
        for r in by_doc.all()
    ]

    return {
        "total_claims": stats.count,
        "total_revenue": float(stats.revenue or 0),
        "avg_payment": round(float(stats.avg_payment or 0), 2),
        "cost_per_dose": gado_cost_per_dose,
        "total_cost": total_cost,
        "margin": round(margin, 2),
        "margin_pct": round(margin / float(stats.revenue or 1) * 100, 1),
        "revenue_per_dollar_cost": round(float(stats.revenue or 0) / total_cost, 2) if total_cost > 0 else 0,
        "by_modality": by_modality,
        "by_year": by_year,
        "by_physician": by_physician,
    }


# ---------------------------------------------------------------------------
# F-08: Duplicate Claim Detector
# ---------------------------------------------------------------------------

@router.get("/duplicates")
async def duplicates(
    include_legitimate: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Detect duplicate claims. Respects C.A.P exception (BR-01)."""
    # Find groups with same patient + date + scan + modality having > 1 record
    dup_query = (
        select(
            BillingRecord.patient_name,
            BillingRecord.service_date,
            BillingRecord.scan_type,
            BillingRecord.modality,
            func.count(BillingRecord.id).label("count"),
            func.array_agg(BillingRecord.id).label("ids"),
            func.array_agg(BillingRecord.description).label("descriptions"),
            func.array_agg(BillingRecord.total_payment).label("payments"),
            func.array_agg(BillingRecord.insurance_carrier).label("carriers"),
        )
        .group_by(
            BillingRecord.patient_name,
            BillingRecord.service_date,
            BillingRecord.scan_type,
            BillingRecord.modality,
        )
        .having(func.count(BillingRecord.id) > 1)
        .order_by(func.count(BillingRecord.id).desc())
    )
    result = await db.execute(dup_query)

    groups = []
    cap_excluded = 0
    for row in result.all():
        descriptions = [str(d or "").upper() for d in row.descriptions]
        is_cap = any("C.A.P" in d or d == "CAP" for d in descriptions)

        if is_cap and not include_legitimate:
            cap_excluded += 1
            continue

        groups.append({
            "patient_name": row.patient_name,
            "service_date": row.service_date.isoformat() if row.service_date else None,
            "scan_type": row.scan_type,
            "modality": row.modality,
            "count": row.count,
            "ids": list(row.ids),
            "descriptions": list(row.descriptions),
            "payments": [float(p or 0) for p in row.payments],
            "carriers": list(row.carriers),
            "is_cap_exception": is_cap,
        })

    return {
        "duplicate_groups": groups,
        "total_groups": len(groups),
        "cap_excluded": cap_excluded,
        "total_duplicate_records": sum(g["count"] for g in groups),
    }


# ---------------------------------------------------------------------------
# F-16: Denial Reason Code Analytics
# ---------------------------------------------------------------------------

@router.get("/denial-analytics")
async def denial_analytics(
    carrier: str | None = None,
    top_n: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Denial reason code analytics — Pareto analysis by frequency and dollar amount."""
    from backend.app.revenue.denial_actions import get_denial_detail

    base = select(
        BillingRecord.denial_reason_code,
        func.count(BillingRecord.id).label("count"),
        func.sum(BillingRecord.total_payment).label("total_paid"),
        BillingRecord.insurance_carrier,
        BillingRecord.modality,
    ).where(BillingRecord.denial_status.is_not(None))

    if carrier:
        base = base.where(BillingRecord.insurance_carrier == carrier)

    # By reason code
    by_reason = await db.execute(
        select(
            BillingRecord.denial_reason_code,
            func.count(BillingRecord.id).label("count"),
        )
        .where(BillingRecord.denial_status.is_not(None))
        .where(BillingRecord.denial_reason_code.is_not(None))
        .group_by(BillingRecord.denial_reason_code)
        .order_by(func.count(BillingRecord.id).desc())
        .limit(top_n)
    )
    reasons = []
    total_denied = 0
    for r in by_reason.all():
        detail = get_denial_detail(r.denial_reason_code)
        total_denied += r.count
        reasons.append({
            "code": r.denial_reason_code,
            "description": detail.get("carc_description", "Unknown"),
            "count": r.count,
            "recommended_action": detail.get("recommended_action", "REVIEW"),
            "recoverable": detail.get("recoverable", False),
        })

    # Cumulative % for Pareto
    running = 0
    for r in reasons:
        running += r["count"]
        r["cumulative_pct"] = round(running / total_denied * 100, 1) if total_denied > 0 else 0

    # By carrier
    by_carrier_result = await db.execute(
        select(
            BillingRecord.insurance_carrier,
            func.count(BillingRecord.id).label("count"),
        )
        .where(BillingRecord.denial_status.is_not(None))
        .group_by(BillingRecord.insurance_carrier)
        .order_by(func.count(BillingRecord.id).desc())
        .limit(10)
    )
    by_carrier = [
        {"carrier": r.insurance_carrier, "count": r.count}
        for r in by_carrier_result.all()
    ]

    # By modality
    by_modality_result = await db.execute(
        select(
            BillingRecord.modality,
            func.count(BillingRecord.id).label("count"),
        )
        .where(BillingRecord.denial_status.is_not(None))
        .group_by(BillingRecord.modality)
        .order_by(func.count(BillingRecord.id).desc())
    )
    by_modality = [
        {"modality": r.modality, "count": r.count}
        for r in by_modality_result.all()
    ]

    return {
        "by_reason": reasons,
        "by_carrier": by_carrier,
        "by_modality": by_modality,
        "total_denied": total_denied,
    }
