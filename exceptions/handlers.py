import logging
from fastapi import Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from exceptions.custom_exceptions import BaseAppException
from utils.response_helpers import error_response

logger = logging.getLogger(__name__)

def setup_exception_handlers(app):

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        logger.warning(f"HTTPException at {request.url.path}: {exc.detail}")
        return error_response(exc.detail, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning(f"Validation error at {request.url.path}: {exc.errors()}")
        return JSONResponse(
            content={
                "success": False,
                "data": None,
                "error": "Invalid or missing request fields",
                "details": exc.errors(),
            },
            status_code=422
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled Exception at {request.url.path}: {exc}")
        return error_response("Something went wrong on the server", status_code=500)
    
    @app.exception_handler(BaseAppException)
    async def app_exception_handler(request: Request, exc: BaseAppException):
        return error_response(exc.message, status_code=exc.status_code)