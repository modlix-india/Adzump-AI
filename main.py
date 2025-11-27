from dotenv import load_dotenv
from fastapi.exceptions import RequestValidationError

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from apis.ads_api import router as ads_router
from apis.chat_api import router as chat_router
from apis.assets_api import router as assets_router
from apis.business_api import router as business_router
from feedback.keyword.api import router as feedback_router

from db import db_session
from utils.response_helpers import error_response

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


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTPException at {request.url.path}: {exc.detail}")
    return error_response(exc.detail, status_code=exc.status_code)

@app.exception_handler(SQLAlchemyError)
async def db_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.exception(f"Database Error at {request.url.path}: {exc}")
    return error_response("A database error occurred.", status_code=500)

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    logger.warning(f"ValueError at {request.url.path}: {exc}")
    return error_response(str(exc), status_code=400)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled Exception at {request.url.path}: {exc}")
    return error_response("Something went wrong on the server", status_code=500)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error at {request.url.path}: {exc.errors()}")
    return error_response("Invalid or missing request fields", status_code=422)
