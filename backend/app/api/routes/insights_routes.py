"""API routes for knowledge graph, recommendations, and session logs."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db
from backend.app.analytics.knowledge_graph import build_knowledge_graph, get_entity_neighborhood
from backend.app.analytics.recommendations import generate_all_recommendations, persist_recommendations
from backend.app.analytics.session_log import (
    generate_session_report, get_session_briefing, update_insight_status,
)

router = APIRouter()


# --- Knowledge Graph ---

@router.get("/graph")
async def knowledge_graph(db: AsyncSession = Depends(get_db)):
    """Build and return the full knowledge graph."""
    return await build_knowledge_graph(db)


@router.get("/graph/entity/{entity_type}/{entity_id}")
async def entity_neighborhood(
    entity_type: str,
    entity_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get all connections for a specific entity."""
    return await get_entity_neighborhood(db, entity_type, entity_id)


# --- Recommendations ---

@router.get("/recommendations")
async def recommendations(
    persist: bool = Query(False, description="Save new insights to database"),
    db: AsyncSession = Depends(get_db),
):
    """Generate all recommendations from billing data analysis."""
    recs = await generate_all_recommendations(db)

    saved = 0
    if persist:
        saved = await persist_recommendations(db, recs)

    return {
        "recommendations": recs,
        "total": len(recs),
        "total_impact": sum(r.get("estimated_impact", 0) or 0 for r in recs),
        "persisted": saved,
    }


# --- Session Reports ---

@router.get("/report")
async def session_report(db: AsyncSession = Depends(get_db)):
    """Generate a full session report for AI conversation continuity."""
    return await generate_session_report(db)


@router.get("/briefing")
async def session_briefing(db: AsyncSession = Depends(get_db)):
    """Quick briefing text for a new AI session."""
    text = await get_session_briefing(db)
    return {"briefing": text}


class InsightStatusUpdate(BaseModel):
    status: str
    notes: str | None = None


@router.post("/{insight_id}/status")
async def update_status(
    insight_id: int,
    body: InsightStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an insight's lifecycle status."""
    return await update_insight_status(db, insight_id, body.status, body.notes)
