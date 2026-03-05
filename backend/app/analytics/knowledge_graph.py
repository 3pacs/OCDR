"""Knowledge Graph Engine.

Builds an in-memory graph of entity relationships from billing data.
Entities: Payers, Physicians, Modalities, Patients, Denial Codes.
Edges weighted by financial impact, volume, and trend direction.

The graph powers recommendations and surfaces hidden patterns:
- Which payer+modality combos lose the most money
- Which physicians drive the most denials
- Which denial codes cluster by payer
- Revenue flow paths and bottlenecks
"""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import String, select, func, case, extract
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord
from backend.app.models.payer import FeeSchedule


async def build_knowledge_graph(db: AsyncSession) -> dict:
    """Build the full knowledge graph from all billing data.

    Returns a graph structure with nodes, edges, and computed metrics.
    """
    nodes = {}
    edges = []
    metrics = {}

    # --- 1. Payer nodes with financial profile ---
    payer_q = (
        select(
            BillingRecord.insurance_carrier.label("carrier"),
            func.count().label("claim_count"),
            func.sum(BillingRecord.total_payment).label("total_revenue"),
            func.sum(BillingRecord.primary_payment).label("total_primary"),
            func.sum(BillingRecord.secondary_payment).label("total_secondary"),
            func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied_count"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
            func.min(BillingRecord.service_date).label("first_service"),
            func.max(BillingRecord.service_date).label("last_service"),
        )
        .group_by(BillingRecord.insurance_carrier)
    )
    payer_result = await db.execute(payer_q)
    for r in payer_result:
        node_id = f"payer:{r.carrier}"
        denial_rate = round(r.denied_count / r.claim_count * 100, 1) if r.claim_count else 0
        nodes[node_id] = {
            "id": node_id,
            "type": "PAYER",
            "label": r.carrier,
            "claim_count": r.claim_count,
            "total_revenue": float(r.total_revenue or 0),
            "avg_payment": float(r.avg_payment or 0),
            "denied_count": r.denied_count,
            "denial_rate": denial_rate,
            "first_service": str(r.first_service) if r.first_service else None,
            "last_service": str(r.last_service) if r.last_service else None,
        }

    # --- 2. Physician nodes ---
    phys_q = (
        select(
            BillingRecord.referring_doctor.label("doctor"),
            func.count().label("referral_count"),
            func.sum(BillingRecord.total_payment).label("total_revenue"),
            func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied_count"),
        )
        .group_by(BillingRecord.referring_doctor)
    )
    phys_result = await db.execute(phys_q)
    for r in phys_result:
        node_id = f"physician:{r.doctor}"
        nodes[node_id] = {
            "id": node_id,
            "type": "PHYSICIAN",
            "label": r.doctor,
            "referral_count": r.referral_count,
            "total_revenue": float(r.total_revenue or 0),
            "denied_count": r.denied_count,
            "denial_rate": round(r.denied_count / r.referral_count * 100, 1) if r.referral_count else 0,
        }

    # --- 3. Modality nodes ---
    mod_q = (
        select(
            BillingRecord.modality.label("modality"),
            func.count().label("scan_count"),
            func.sum(BillingRecord.total_payment).label("total_revenue"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
            func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied_count"),
        )
        .group_by(BillingRecord.modality)
    )
    mod_result = await db.execute(mod_q)
    for r in mod_result:
        node_id = f"modality:{r.modality}"
        nodes[node_id] = {
            "id": node_id,
            "type": "MODALITY",
            "label": r.modality,
            "scan_count": r.scan_count,
            "total_revenue": float(r.total_revenue or 0),
            "avg_payment": float(r.avg_payment or 0),
            "denied_count": r.denied_count,
        }

    # --- 4. Denial code nodes ---
    denial_q = (
        select(
            BillingRecord.denial_reason_code.label("code"),
            func.count().label("count"),
        )
        .where(BillingRecord.denial_reason_code.isnot(None))
        .group_by(BillingRecord.denial_reason_code)
    )
    denial_result = await db.execute(denial_q)
    for r in denial_result:
        node_id = f"denial_code:{r.code}"
        nodes[node_id] = {
            "id": node_id,
            "type": "DENIAL_CODE",
            "label": r.code,
            "count": r.count,
        }

    # --- 5. Edges: Payer <-> Modality (revenue flow) ---
    pm_q = (
        select(
            BillingRecord.insurance_carrier.label("carrier"),
            BillingRecord.modality.label("modality"),
            func.count().label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
            func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
        )
        .group_by(BillingRecord.insurance_carrier, BillingRecord.modality)
    )
    pm_result = await db.execute(pm_q)
    for r in pm_result:
        edges.append({
            "source": f"payer:{r.carrier}",
            "target": f"modality:{r.modality}",
            "type": "PAYS_FOR",
            "weight": float(r.revenue or 0),
            "count": r.count,
            "avg_payment": float(r.avg_payment or 0),
            "denied": r.denied,
            "denial_rate": round(r.denied / r.count * 100, 1) if r.count else 0,
        })

    # --- 6. Edges: Physician <-> Payer (referral patterns) ---
    dp_q = (
        select(
            BillingRecord.referring_doctor.label("doctor"),
            BillingRecord.insurance_carrier.label("carrier"),
            func.count().label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .group_by(BillingRecord.referring_doctor, BillingRecord.insurance_carrier)
        .having(func.count() >= 5)  # Only significant relationships
    )
    dp_result = await db.execute(dp_q)
    for r in dp_result:
        edges.append({
            "source": f"physician:{r.doctor}",
            "target": f"payer:{r.carrier}",
            "type": "REFERS_TO",
            "weight": float(r.revenue or 0),
            "count": r.count,
        })

    # --- 7. Edges: Payer <-> Denial Code ---
    pd_q = (
        select(
            BillingRecord.insurance_carrier.label("carrier"),
            BillingRecord.denial_reason_code.label("code"),
            func.count().label("count"),
        )
        .where(BillingRecord.denial_reason_code.isnot(None))
        .group_by(BillingRecord.insurance_carrier, BillingRecord.denial_reason_code)
    )
    pd_result = await db.execute(pd_q)
    for r in pd_result:
        edges.append({
            "source": f"payer:{r.carrier}",
            "target": f"denial_code:{r.code}",
            "type": "DENIES_WITH",
            "weight": r.count,
            "count": r.count,
        })

    # --- 8. Trend analysis (YoY by payer) ---
    trend_q = (
        select(
            BillingRecord.insurance_carrier.label("carrier"),
            func.coalesce(BillingRecord.service_year, extract("year", BillingRecord.service_date).cast(String)).label("year"),
            func.count().label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .group_by(
            BillingRecord.insurance_carrier,
            func.coalesce(BillingRecord.service_year, extract("year", BillingRecord.service_date).cast(String)),
        )
        .order_by(BillingRecord.insurance_carrier)
    )
    trend_result = await db.execute(trend_q)
    trends = defaultdict(list)
    for r in trend_result:
        trends[r.carrier].append({
            "year": r.year,
            "count": r.count,
            "revenue": float(r.revenue or 0),
        })
    metrics["payer_trends"] = dict(trends)

    # --- 9. Global metrics ---
    total_q = select(
        func.count().label("total"),
        func.sum(BillingRecord.total_payment).label("revenue"),
        func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
    )
    total_result = (await db.execute(total_q)).one()
    metrics["totals"] = {
        "total_claims": total_result.total,
        "total_revenue": float(total_result.revenue or 0),
        "total_denied": total_result.denied,
        "denial_rate": round(total_result.denied / total_result.total * 100, 1) if total_result.total else 0,
    }

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "metrics": metrics,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


async def get_entity_neighborhood(
    db: AsyncSession,
    entity_type: str,
    entity_id: str,
) -> dict:
    """Get all connections for a specific entity in the graph.

    Example: get_entity_neighborhood("PAYER", "M/M") returns all
    modalities, physicians, denial codes connected to M/M.
    """
    graph = await build_knowledge_graph(db)

    target_id = f"{entity_type.lower()}:{entity_id}"

    connected_edges = [
        e for e in graph["edges"]
        if e["source"] == target_id or e["target"] == target_id
    ]

    connected_node_ids = set()
    for e in connected_edges:
        connected_node_ids.add(e["source"])
        connected_node_ids.add(e["target"])

    connected_nodes = [n for n in graph["nodes"] if n["id"] in connected_node_ids]
    center_node = next((n for n in graph["nodes"] if n["id"] == target_id), None)

    return {
        "center": center_node,
        "nodes": connected_nodes,
        "edges": connected_edges,
    }
