from typing import Any, Optional, Dict


class MetaAPIError(Exception):
    """Exception raised when Meta Graph API returns an error."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_data: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.error_data = error_data or {}
        super().__init__(message)


class MetaAPIContractError(MetaAPIError):
    """Exception raised when Meta API responds successfully but breaks the expected data contract (e.g. missing 'id')."""

    pass


class MetaAdCreationError(Exception):
    """Exception raised when the orchestration of Ad creation fails at a specific stage."""

    def __init__(
        self,
        failed_stage: str,
        existing_ids: Dict[str, Optional[str]],
        original_exc: Exception,
    ):
        self.failed_stage = failed_stage
        self.existing_ids = existing_ids
        self.original_exc = original_exc
        super().__init__(f"Ad creation failed at stage: {failed_stage}")

    @property
    def meta_error(self) -> Dict[str, Any]:
        """Return structured error information from the underlying exception.
 
        Extracts the Meta 'error' object if the exception is a MetaAPIError, 
        otherwise returns a standard dictionary with the exception message.
        """
        if isinstance(self.original_exc, MetaAPIError):
            return self.original_exc.error_data.get("error", {})
        return {"message": str(self.original_exc)}

    @property
    def status_code(self) -> int:
        """Extract status code from the original exception, defaulting to 400."""
        return getattr(self.original_exc, "status_code", 400)

    @property
    def message(self) -> str:
        """Extract human-readable message from the original exception."""
        return getattr(self.original_exc, "message", str(self.original_exc))
