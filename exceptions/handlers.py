from fastapi import Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from adapters.meta.exceptions import MetaAPIError
from exceptions.custom_exceptions import BaseAppException
from adapters.meta.exceptions import MetaAdCreationError
from utils.response_helpers import error_response
from structlog import get_logger  # type: ignore

logger = get_logger(__name__)


def setup_exception_handlers(app):
    # Handlers are ordered most-specific → least-specific for readability.
    # FastAPI resolves by exact class match, but this mirrors Python's try/except convention.

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        logger.error(
            "Validation error",
            path=request.url.path,
            errors=exc.errors(),
        )
        formatted_errors = [
            {
                "loc": err.get("loc", []),
                "msg": err.get("msg"),
                "type": err.get("type", "value_error"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            content={
                "success": False,
                "data": None,
                "error": "Invalid or missing request fields",
                "details": formatted_errors,
            },
            status_code=422,
        )

    @app.exception_handler(MetaAdCreationError)
    async def meta_ad_creation_error_handler(
        request: Request, exc: MetaAdCreationError
    ):
        logger.error(
            "MetaAdCreationError",
            path=request.url.path,
            message=exc.message,
            failed_stage=exc.failed_stage,
            meta_error=exc.meta_error,
        )
        return error_response(
            message=exc.message,
            status_code=exc.status_code,
            details={
                "failed_stage": exc.failed_stage,
                "meta_error": exc.meta_error,
                "ids": exc.existing_ids,
            },
        )

    @app.exception_handler(MetaAPIError)
    async def meta_api_error_handler(request: Request, exc: MetaAPIError):
        logger.error(
            "Meta API error",
            path=request.url.path,
            message=exc.message,
        )
        return error_response(exc.message, status_code=exc.status_code)

    @app.exception_handler(BaseAppException)
    async def app_exception_handler(request: Request, exc: BaseAppException):
        details = getattr(exc, "details", None)
        log_method = logger.error if exc.status_code >= 500 else logger.warning
        log_method(
            "Application error",
            path=request.url.path,
            message=exc.message,
            status_code=exc.status_code,
            details=details,
        )
        return error_response(exc.message, details=details, status_code=exc.status_code)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        logger.warning(
            "HTTP exception",
            path=request.url.path,
            detail=exc.detail,
            status_code=exc.status_code,
        )
        return error_response(exc.detail, status_code=exc.status_code)

    @app.exception_handler(SQLAlchemyError)
    async def db_exception_handler(request: Request, exc: SQLAlchemyError):
        logger.exception(
            "Database error",
            path=request.url.path,
            error=str(exc),
        )
        return error_response("A database error occurred.", status_code=500)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception(
            "Unhandled exception",
            path=request.url.path,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return error_response("Something went wrong on the server", status_code=500)
