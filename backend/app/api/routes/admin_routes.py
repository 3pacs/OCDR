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
