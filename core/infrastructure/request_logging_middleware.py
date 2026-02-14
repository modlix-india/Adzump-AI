"""Middleware that logs one canonical line per HTTP request with context."""

import time
import uuid

import structlog
import structlog.contextvars
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger("request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.endswith("/health"):
            return await call_next(request)

        request_id = uuid.uuid4().hex[:8]
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        start = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.info(
                "request_completed",
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.error("request_failed", duration_ms=duration_ms)
            raise
        finally:
            structlog.contextvars.unbind_contextvars("request_id", "method", "path")
