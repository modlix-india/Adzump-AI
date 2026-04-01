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


class MetaAPIContractError(MetaAPIError):
    """Exception raised when Meta API responds successfully but breaks the expected data contract (e.g. missing 'id')."""
    pass


class MetaAdCreationError(Exception):
    """Exception raised when the orchestration of Ad creation fails at a specific stage."""
    def __init__(self, failed_stage: str, existing_ids: dict, original_exc: Exception):
        self.failed_stage = failed_stage
        self.existing_ids = existing_ids
        self.original_exc = original_exc
        super().__init__(f"Ad creation failed at stage: {failed_stage}")
