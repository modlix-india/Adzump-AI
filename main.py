from fastapi import FastAPI
from apis.ads_api import router as ads_router
from apis.chat_api import router as chat_router
from apis.assets_api import router as assets_router
from apis.business_api import router as business_router
from apis.prediction_api import router as prediction_router
from contextlib import asynccontextmanager
from utils import httpx_utils
from dotenv import load_dotenv
import structlog
import logging

load_dotenv()

# Configure structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),  # Use JSONRenderer for production
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await httpx_utils.close_http_client()


app = FastAPI(title="Ads AI: Automate, Optimize, Analyze", lifespan=lifespan)

app.include_router(ads_router)
app.include_router(chat_router)
app.include_router(assets_router)
app.include_router(business_router)
app.include_router(prediction_router)
