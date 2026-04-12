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

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        logger.warning(f"HTTPException at {request.url.path}: {exc.detail}")
        return error_response(exc.detail, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        logger.warning(f"Validation error at {request.url.path}: {exc.errors()}")
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

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled Exception at {request.url.path}: {exc}")
        return error_response("Something went wrong on the server", status_code=500)

    @app.exception_handler(BaseAppException)
    async def app_exception_handler(request: Request, exc: BaseAppException):
        details = getattr(exc, "details", None)
        logger.warning(
            f"AppException at {request.url.path}: {exc.message}",
            status_code=exc.status_code,
            details=details,
        )
        return error_response(exc.message, details=details, status_code=exc.status_code)

    @app.exception_handler(SQLAlchemyError)
    async def db_exception_handler(request: Request, exc: SQLAlchemyError):
        logger.exception(f"Database Error at {request.url.path}: {exc}")
        return error_response("A database error occurred.", status_code=500)

    @app.exception_handler(MetaAPIError)
    async def meta_api_error_handler(request: Request, exc: MetaAPIError):
        logger.warning(f"Meta API Error at {request.url.path}: {exc.message}")
        return error_response(exc.message, status_code=exc.status_code)

    @app.exception_handler(MetaAdCreationError)
    async def meta_ad_creation_error_handler(
        request: Request, exc: MetaAdCreationError
    ):
        status_code = getattr(exc.original_exc, "status_code", 400)
        message = getattr(exc.original_exc, "message", str(exc.original_exc))
        meta_error = getattr(exc.original_exc, "error_data", {}).get("error", {})

        logger.warning(
            f"MetaAdCreationError at {request.url.path}: {message}",
            failed_stage=exc.failed_stage,
            meta_error=meta_error,
        )
        return error_response(
            message=message,
            status_code=status_code,
            details={
                "failed_stage": exc.failed_stage,
                "meta_error": meta_error,
                "ids": exc.existing_ids,
            },
        )
