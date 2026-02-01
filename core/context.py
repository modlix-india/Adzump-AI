"""Request-scoped context for auth credentials.

Similar to Java's SecurityContext or Go's context.Context.
Uses Python's contextvars which work correctly with async/await.

Usage:
    # Read in any service/agent
    from core.context import auth_context
    token = auth_context.access_token
    client = auth_context.client_code
"""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class AuthContext:
    access_token: str = ""
    client_code: str = ""
    x_forwarded_host: str = ""
    x_forwarded_port: str = ""


_auth_context: ContextVar[AuthContext] = ContextVar(
    "auth_context", default=AuthContext()
)


def set_auth_context(
    access_token: str,
    client_code: str,
    x_forwarded_host: str = "",
    x_forwarded_port: str = "",
) -> None:
    """Set auth context for current request. Called by middleware."""
    _auth_context.set(
        AuthContext(
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port,
        )
    )


def get_auth_context() -> AuthContext:
    """Get auth context for current request."""
    return _auth_context.get()


# Convenience accessor
class _AuthContextAccessor:
    """Accessor for reading auth context values directly."""

    @property
    def access_token(self) -> str:
        return _auth_context.get().access_token

    @property
    def client_code(self) -> str:
        return _auth_context.get().client_code

    @property
    def x_forwarded_host(self) -> str:
        return _auth_context.get().x_forwarded_host

    @property
    def x_forwarded_port(self) -> str:
        return _auth_context.get().x_forwarded_port


auth_context = _AuthContextAccessor()
