from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from apis.ads_api import router as ads_router
from apis.chat_api import router as chat_router
from apis.assets_api import router as assets_router
from apis.business_api import router as business_router
from mlops.google_search.performance.prediction_api import router as performance_router
from mlops.google_search.budget_prediction.api import router as budget_router
from apis.maps import router as maps_router
from exceptions.handlers import setup_exception_handlers
from feedback.keyword.api import router as feedback_router

from db import db_session
from config.logging_config import setup_logging
from services.geo_target_service import GeoTargetService
from structlog import get_logger  # type: ignore

from dotenv import load_dotenv

load_dotenv()

# Setup structlog for JSON structured logging
setup_logging()

# Get structlog logger
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = None
    try:
        # Startup: create engine and validate DB connectivity
        engine = db_session.get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connected", component="db")

        # Make engine available to routes/services via app.state
        app.state.engine = engine
        yield
    except Exception as e:
        logger.error(
            "Database connection failed", component="db", error=str(e), exc_info=True
        )
        # Re-raise to fail-fast on bad DB config
        raise
    finally:
        # Shutdown: dispose the engine/pool only if it was created
        if engine is not None:
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
        await GeoTargetService.close_client()


app = FastAPI(title="Ads AI: Automate, Optimize, Analyze", lifespan=lifespan)


@app.get("/health")
async def health_check():
    logger.info("Health check requested", endpoint="/health")
    return {"status": "healthy", "service": "ds-service"}


app.include_router(ads_router)
app.include_router(chat_router)
app.include_router(assets_router)
app.include_router(business_router)
app.include_router(maps_router)
app.include_router(performance_router)
app.include_router(budget_router)

app.include_router(feedback_router)

setup_exception_handlers(app)
