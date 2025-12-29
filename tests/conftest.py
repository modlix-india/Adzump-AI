"""
Pytest configuration and fixtures for keyword feedback tests.
Provides database setup, cleanup, and sample data fixtures.
"""

import os
import pytest_asyncio  # type: ignore
from typing import AsyncGenerator
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy import text
from pathlib import Path

# Try to load .env.test first, then fall back to regular .env
env_test_path = Path(__file__).parent / ".env.test"
if env_test_path.exists():
    load_dotenv(env_test_path, override=True)
else:
    # Fall back to project root .env
    load_dotenv(override=False)


@pytest_asyncio.fixture(scope="function")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set for tests")

    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )

    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Create a new database session for each test."""
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        yield session

# TODO: This is a hack to cleanup test data. We should use a more robust solution.
@pytest_asyncio.fixture
async def cleanup_test_data(test_session: AsyncSession):
    """
    Cleanup fixture to remove inserted test data from rag_chunks after a test.
    """
    yield
    # Remove test-inserted data
    await test_session.execute(
        text("DELETE FROM rag_chunks WHERE client_code LIKE 'TEST_CLIENT_%'")
    )
    await test_session.commit()
