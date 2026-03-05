"""API routes for auto-matching, crosswalk, and match review."""

import logging
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db
from backend.app.matching.auto_matcher import (
    run_auto_match,
    get_match_summary,
    get_unmatched_claims,
    get_matched_claims,
)
from backend.app.matching.pattern_clusterer import (
    analyze_crosswalk,
    propagate_topaz_ids,
    get_crosswalk_stats,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Auto-Matching ---

@router.post("/run")
async def trigger_auto_match(db: AsyncSession = Depends(get_db)):
    """Run the 6-pass auto-matching engine on all unmatched ERA claims."""
    try:
        result = await run_auto_match(db)
        return result
    except Exception as e:
        logger.exception(f"Auto-match failed: {e}")
        return {"error": str(e)}


@router.get("/summary")
async def match_summary(db: AsyncSession = Depends(get_db)):
    """Get current matching statistics."""
    return await get_match_summary(db)


@router.get("/unmatched")
async def list_unmatched(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List unmatched ERA claims for manual review."""
    return await get_unmatched_claims(db, page, per_page)


@router.get("/matched")
async def list_matched(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List matched ERA claims with billing record details."""
    return await get_matched_claims(db, page, per_page)


# --- Crosswalk (Chart Number <-> Topaz ID) ---

@router.get("/crosswalk/stats")
async def crosswalk_stats(db: AsyncSession = Depends(get_db)):
    """Get crosswalk coverage stats."""
    return await get_crosswalk_stats(db)


@router.get("/crosswalk/analyze")
async def crosswalk_analyze(db: AsyncSession = Depends(get_db)):
    """Analyze chart_number <-> topaz_id patterns from confirmed matches."""
    return await analyze_crosswalk(db)


class PropagateRequest(BaseModel):
    offset: int | None = None


@router.post("/crosswalk/propagate")
async def crosswalk_propagate(
    body: PropagateRequest = PropagateRequest(),
    db: AsyncSession = Depends(get_db),
):
    """Apply discovered offset pattern to assign topaz_id to unlinked billing records."""
    return await propagate_topaz_ids(db, offset=body.offset)
