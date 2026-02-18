import os
from dotenv import load_dotenv

load_dotenv()  # Load env vars before other imports
from config.logging_config import setup_logging
from fastapi import FastAPI
from apis.ads_api import router as ads_router
from apis.chat_api import router as chat_router
from apis.assets_api import router as assets_router
from apis.business_api import router as business_router
from mlops.google_search.performance.prediction_api import router as performance_router
from mlops.google_search.budget_prediction.api import router as budget_router
from apis.maps import router as maps_router
from exceptions.handlers import setup_exception_handlers
from feedback.keyword.api import router as feedback_router
from core.infrastructure.middleware import AuthContextMiddleware
from core.infrastructure.request_logging_middleware import RequestLoggingMiddleware
from core.infrastructure.lifecycle import lifespan
from core.metadata import SERVICE_NAME, APP_TITLE
from api.meta import router as meta_ads_router
from api.optimization import router as optimization_router


setup_logging()

app = FastAPI(title=APP_TITLE, lifespan=lifespan)

# Auth context middleware - extracts access-token and clientCode headers into request context.
# Headers are optional here; endpoints requiring auth should validate via their own logic.
app.add_middleware(AuthContextMiddleware)
# TODO: Add debugKey middleware — accept a client-supplied debug key via header,
# bind it to structlog contextvars (like request_id), so logs can be traced
# end-to-end across services using the same key.
app.add_middleware(RequestLoggingMiddleware)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": SERVICE_NAME}


app.include_router(ads_router)
app.include_router(chat_router)
app.include_router(assets_router)
app.include_router(business_router)
app.include_router(maps_router)
if not os.getenv("SKIP_ML_MODELS"):
    app.include_router(performance_router)
    app.include_router(budget_router)

app.include_router(feedback_router)
app.include_router(meta_ads_router)
app.include_router(optimization_router)

setup_exception_handlers(app)
