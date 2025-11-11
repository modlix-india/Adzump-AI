from dotenv import load_dotenv
from fastapi.exceptions import RequestValidationError
load_dotenv()

import logging
from fastapi import FastAPI, HTTPException, Request
from apis.ads_api import router as ads_router
from apis.chat_api import router as chat_router
from apis.assets_api import router as assets_router
from apis.business_api import router as business_router
from utils.response_helpers import error_response


logger = logging.getLogger(__name__)

app = FastAPI(title="Ads AI: Automate, Optimize, Analyze")

app.include_router(ads_router)
app.include_router(chat_router)
app.include_router(assets_router)
app.include_router(business_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTPException at {request.url.path}: {exc.detail}")
    return error_response(exc.detail, status_code=exc.status_code)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled Exception at {request.url.path}: {exc}")
    return error_response("Something went wrong on the server", status_code=500)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error at {request.url.path}: {exc.errors()}")
    return error_response("Invalid or missing request fields", status_code=422)