from typing import Any, Optional


class MetaAPIError(Exception):
    """Exception raised when Meta Graph API returns an error."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_data: Optional[dict[str, Any]] = None
    ):
        self.message = message
        self.status_code = status_code
        self.error_data = error_data or {}
        super().__init__(message)
