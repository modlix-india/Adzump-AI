import os
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

_engine: Optional[AsyncEngine] = None


def get_engine(url: Optional[str] = None) -> AsyncEngine:
    """Return a singleton AsyncEngine, creating it on first use."""
    global _engine
    if _engine is None:
        dsn = url or os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL is not set. Export it or load it in your entrypoint before calling get_engine()."
            )
        _engine = create_async_engine(
            dsn,
            pool_pre_ping=True,
            pool_size=20,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
        )
    return _engine
