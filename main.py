from dotenv import load_dotenv

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from apis.ads_api import router as ads_router
from apis.chat_api import router as chat_router
from apis.assets_api import router as assets_router
from apis.business_api import router as business_router
from exceptions.handlers import setup_exception_handlers
from feedback.keyword.api import router as feedback_router

from db import db_session

load_dotenv()

logging.basicConfig(level=logging.INFO)  # or use LOG_LEVEL from env

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create engine and validate DB connectivity
    engine = db_session.get_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logging.getLogger("db").info("Database connected (startup ping OK)")

        # Make engine available to routes/services via app.state
        app.state.engine = engine
        yield
    except Exception as e:
        logging.getLogger("db").exception("Database connection failed: %s", e)
        # Re-raise to fail-fast on bad DB config
        raise
    finally:
        # Shutdown: dispose the engine/pool
        try:
            # AsyncEngine.dispose() is awaitable
            await app.state.engine.dispose()  # type: ignore[attr-defined]
            logging.getLogger("db").info("Database engine disposed")
        except Exception as e:
            logging.getLogger("db").exception("Error during DB dispose: %s", e)


app = FastAPI(title="Ads AI: Automate, Optimize, Analyze", lifespan=lifespan)

app.include_router(ads_router)
app.include_router(chat_router)
app.include_router(assets_router)
app.include_router(business_router)
app.include_router(feedback_router)


setup_exception_handlers(app)