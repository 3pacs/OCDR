"""Database session management for PostgreSQL and DuckDB."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from backend.app.core.config import settings

# PostgreSQL async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    pool_size=20,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency for database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# DuckDB connection helper (synchronous — used for bulk analytics)
def get_duckdb():
    """Get a DuckDB connection for bulk analytics operations."""
    import duckdb
    return duckdb.connect(settings.DUCKDB_PATH)
