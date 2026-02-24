"""Denial Reason Code Analytics (F-16).

Aggregates CAS reason codes from ERA data: top by frequency,
top by $ amount, by carrier, by modality, with Pareto analysis.
"""

from sqlalchemy import func

from app.models import db, EraClaimLine, EraPayment


# ANSI X12 CAS Reason Code reference (common codes)
REASON_CODE_DESCRIPTIONS = {
    "1": "Deductible",
    "2": "Coinsurance",
    "3": "Copay",
    "4": "Not covered / benefit exceeded",
    "5": "Not covered under plan",
    "9": "Not furnished directly to patient",
    "16": "Missing / incomplete information",
    "18": "Exact duplicate claim",
    "22": "Coordination of Benefits",
    "23": "Payment adjusted (charges paid by payer)",
    "24": "Charges covered under capitation",
    "26": "Expenses incurred prior to coverage",
    "27": "Expenses incurred after coverage terminated",
    "29": "Time limit for filing has expired",
    "31": "Not the patient's responsibility (provider issue)",
    "35": "Lifetime benefit maximum reached",
    "39": "Services denied at time of service",
    "40": "Charges do not meet qualifications for emergent care",
    "42": "Charges exceed our fee schedule or maximum allowable",
    "45": "Exceeds fee schedule / charge limit",
    "49": "Non-covered service because not deemed a medical necessity",
    "50": "Non-covered — not deemed medical necessity by payer",
    "59": "Processed based on multiple or concurrent procedure rules",
    "89": "Professional component charges processed separately",
    "96": "Non-covered charge(s)",
    "97": "Benefit included in allowance for another service",
    "109": "Not covered by this payer / plan",
    "119": "Additional payment for this service is included in payment for another",
    "125": "Payment adjusted — submission error(s)",
    "136": "Claim/service not payable under plan provisions",
    "167": "Diagnosis is not covered",
    "197": "Precertification/authorization absent",
    "204": "Service not covered when performed in this setting",
    "226": "Mandated federal/state/local requirement not met",
    "234": "Not covered for this combination of patient / provider / service",
    "236": "Not medically necessary or not medically appropriate",
    "242": "Services not provided by network providers",
    "253": "Sequestration adjustment",
}


def get_reason_code_description(code):
    """Get human-readable description for a CAS reason code."""
    return REASON_CODE_DESCRIPTIONS.get(str(code), f"Code {code}")


def get_denial_analytics():
    """Get comprehensive denial reason code analytics."""
    # Top reason codes by frequency
    by_frequency = db.session.query(
        EraClaimLine.cas_reason_code,
        func.count(EraClaimLine.id).label("count"),
        func.sum(EraClaimLine.cas_adjustment_amount).label("total_amount"),
    ).filter(
        EraClaimLine.cas_reason_code.isnot(None)
    ).group_by(EraClaimLine.cas_reason_code).order_by(
        func.count(EraClaimLine.id).desc()
    ).limit(20).all()

    # Top by dollar amount
    by_amount = db.session.query(
        EraClaimLine.cas_reason_code,
        func.sum(EraClaimLine.cas_adjustment_amount).label("total_amount"),
        func.count(EraClaimLine.id).label("count"),
    ).filter(
        EraClaimLine.cas_reason_code.isnot(None),
        EraClaimLine.cas_adjustment_amount.isnot(None),
    ).group_by(EraClaimLine.cas_reason_code).order_by(
        func.sum(EraClaimLine.cas_adjustment_amount).desc()
    ).limit(20).all()

    # By group code
    by_group = db.session.query(
        EraClaimLine.cas_group_code,
        func.count(EraClaimLine.id).label("count"),
        func.sum(EraClaimLine.cas_adjustment_amount).label("total_amount"),
    ).filter(
        EraClaimLine.cas_group_code.isnot(None)
    ).group_by(EraClaimLine.cas_group_code).all()

    return {
        "by_frequency": [{
            "reason_code": r.cas_reason_code,
            "description": get_reason_code_description(r.cas_reason_code),
            "count": r.count,
            "total_amount": round(r.total_amount or 0, 2),
        } for r in by_frequency],
        "by_amount": [{
            "reason_code": r.cas_reason_code,
            "description": get_reason_code_description(r.cas_reason_code),
            "total_amount": round(r.total_amount or 0, 2),
            "count": r.count,
        } for r in by_amount],
        "by_group": [{
            "group_code": r.cas_group_code,
            "count": r.count,
            "total_amount": round(r.total_amount or 0, 2),
        } for r in by_group],
    }


def get_denial_pareto():
    """Pareto analysis — 80/20 rule for denial codes."""
    reasons = db.session.query(
        EraClaimLine.cas_reason_code,
        func.sum(EraClaimLine.cas_adjustment_amount).label("total_amount"),
        func.count(EraClaimLine.id).label("count"),
    ).filter(
        EraClaimLine.cas_reason_code.isnot(None),
        EraClaimLine.cas_adjustment_amount.isnot(None),
    ).group_by(EraClaimLine.cas_reason_code).order_by(
        func.sum(EraClaimLine.cas_adjustment_amount).desc()
    ).all()

    grand_total = sum(r.total_amount or 0 for r in reasons)
    cumulative = 0.0
    pareto = []

    for r in reasons:
        cumulative += (r.total_amount or 0)
        pareto.append({
            "reason_code": r.cas_reason_code,
            "description": get_reason_code_description(r.cas_reason_code),
            "amount": round(r.total_amount or 0, 2),
            "count": r.count,
            "cumulative_pct": round((cumulative / grand_total * 100) if grand_total > 0 else 0, 1),
        })

    return {"pareto": pareto, "grand_total": round(grand_total, 2)}


def get_denials_by_carrier():
    """Denial reason codes broken down by insurance carrier."""
    results = db.session.query(
        EraPayment.payer_name,
        EraClaimLine.cas_reason_code,
        func.count(EraClaimLine.id).label("count"),
        func.sum(EraClaimLine.cas_adjustment_amount).label("total_amount"),
    ).join(EraPayment, EraClaimLine.era_payment_id == EraPayment.id).filter(
        EraClaimLine.cas_reason_code.isnot(None)
    ).group_by(EraPayment.payer_name, EraClaimLine.cas_reason_code).order_by(
        EraPayment.payer_name, func.count(EraClaimLine.id).desc()
    ).all()

    carriers = {}
    for r in results:
        payer = r.payer_name or "Unknown"
        if payer not in carriers:
            carriers[payer] = []
        carriers[payer].append({
            "reason_code": r.cas_reason_code,
            "description": get_reason_code_description(r.cas_reason_code),
            "count": r.count,
            "total_amount": round(r.total_amount or 0, 2),
        })

    return carriers


def get_denial_trend():
    """Denial reasons over time (by month)."""
    results = db.session.query(
        func.strftime("%Y-%m", EraPayment.payment_date).label("month"),
        EraClaimLine.cas_group_code,
        func.count(EraClaimLine.id).label("count"),
        func.sum(EraClaimLine.cas_adjustment_amount).label("total_amount"),
    ).join(EraPayment, EraClaimLine.era_payment_id == EraPayment.id).filter(
        EraClaimLine.cas_reason_code.isnot(None),
        EraPayment.payment_date.isnot(None),
    ).group_by(
        func.strftime("%Y-%m", EraPayment.payment_date),
        EraClaimLine.cas_group_code,
    ).order_by("month").all()

    months = {}
    for r in results:
        if r.month not in months:
            months[r.month] = {"month": r.month, "CO": 0, "PR": 0, "OA": 0, "PI": 0, "total": 0}
        group = r.cas_group_code or "OA"
        if group in months[r.month]:
            months[r.month][group] += r.count
        months[r.month]["total"] += r.count

    return sorted(months.values(), key=lambda x: x["month"])
