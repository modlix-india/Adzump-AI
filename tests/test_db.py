"""Test to verify database and environment configuration."""

import os
import pytest


@pytest.mark.asyncio
async def test_environment_setup():
    """Diagnostic test to verify environment is correct."""
    db_url = os.getenv("DATABASE_URL")
    openai_key = os.getenv("OPENAI_API_KEY")

    print(f"DATABASE_URL: {db_url[:30]}..." if db_url else "DATABASE_URL: NOT SET")
    print(f"OPENAI_API_KEY: {'SET' if openai_key else 'NOT SET'}")

    assert db_url is not None, "DATABASE_URL not set"
    assert openai_key is not None, "OPENAI_API_KEY not set"