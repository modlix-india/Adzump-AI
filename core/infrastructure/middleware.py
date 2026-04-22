"""FastAPI middleware for setting request context."""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from core.infrastructure.context import set_auth_context


def _extract_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return auth


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Middleware that populates auth context from request headers."""

    async def dispatch(self, request: Request, call_next):
        timezone_header = request.headers.get("x-timezone")

        kwargs = {
            "access_token": _extract_token(request),
            "client_code": request.headers.get("clientCode", ""),
            "x_forwarded_host": request.headers.get("x-forwarded-host", ""),
            "x_forwarded_port": request.headers.get("x-forwarded-port", ""),
        }

        if timezone_header:
            kwargs["timezone"] = timezone_header

        set_auth_context(**kwargs)
        return await call_next(request)
