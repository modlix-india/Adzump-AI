"""FastAPI middleware for setting request context."""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from core.infrastructure.context import set_auth_context


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Middleware that populates auth context from request headers."""

    async def dispatch(self, request: Request, call_next):
        set_auth_context(
            access_token=request.headers.get("access-token", ""),
            client_code=request.headers.get("clientCode", ""),
            x_forwarded_host=request.headers.get("x-forwarded-host", ""),
            x_forwarded_port=request.headers.get("x-forwarded-port", ""),
        )
        return await call_next(request)
