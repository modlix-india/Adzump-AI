import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
import structlog

from core.infrastructure.http_client import init_http_client, close_http_client
from core.metadata import SERVICE_NAME, VERSION
from db import db_session

logger = structlog.get_logger(__name__)

STARTUP_BANNER = """
╔══════════════════════════════════════════════╗
║  {service} v{version}
║  Python {python} | env: {env} | {log_level}
╚══════════════════════════════════════════════╝"""

SHUTDOWN_BANNER = """
╔══════════════════════════════════════════════╗
║  {service} v{version} shutting down
╚══════════════════════════════════════════════╝"""


async def initialize_database() -> AsyncEngine:
    engine = db_session.get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("Database connected", component="db")
    return engine


async def cleanup_database(engine: AsyncEngine) -> None:
    try:
        await engine.dispose()
        logger.info("Database engine disposed", component="db")
    except Exception as e:
        logger.error(
            "Error during DB dispose",
            component="db",
            error=str(e),
            exc_info=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = None
    try:
        engine = await initialize_database()
        app.state.engine = engine

        init_http_client()
        logger.info("HTTP client initialized", component="http")

        environment = os.getenv("ENVIRONMENT", "local")
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        python_version = sys.version.split()[0]

        print(
            STARTUP_BANNER.format(
                service=SERVICE_NAME,
                version=VERSION,
                python=python_version,
                env=environment,
                log_level=log_level,
            )
        )
        logger.info(
            "Service started",
            service=SERVICE_NAME,
            version=VERSION,
            python=python_version,
            environment=environment,
            log_level=log_level,
        )
        yield
    except Exception as e:
        logger.error(
            "Database connection failed", component="db", error=str(e), exc_info=True
        )
        raise
    finally:
        print(SHUTDOWN_BANNER.format(service=SERVICE_NAME, version=VERSION))
        logger.info("Service shutting down", service=SERVICE_NAME, version=VERSION)
        if engine is not None:
            await cleanup_database(engine)
        await close_http_client()
        logger.info("HTTP client closed", component="http")
