from typing import Optional
from fastapi import status


class BaseAppException(Exception):
    """Base class for all app-specific exceptions."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Optional[dict] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class BusinessValidationException(BaseAppException):
    """Invalid input or business rule violation."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, status.HTTP_422_UNPROCESSABLE_ENTITY, details)


class AIProcessingException(BaseAppException):
    """OpenAI or AI processing failure."""

    def __init__(
        self,
        message: str = "AI model processing failed",
        details: Optional[dict] = None,
    ):
        super().__init__(message, status.HTTP_502_BAD_GATEWAY, details)


class ScraperException(BaseAppException):
    """Website scraping failed."""

    def __init__(
        self,
        message: str = "Failed to scrape website content",
        details: Optional[dict] = None,
    ):
        super().__init__(message, status.HTTP_502_BAD_GATEWAY, details)


class StorageException(BaseAppException):
    """Storage read/write failed."""

    def __init__(
        self,
        message: str = "Error communicating with storage service",
        details: Optional[dict] = None,
    ):
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR, details)


class InternalServerException(BaseAppException):
    """Unexpected error in backend logic."""

    def __init__(
        self, message: str = "Internal server error", details: Optional[dict] = None
    ):
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR, details)


class DatabaseException(BaseAppException):
    """Database operation failed."""

    def __init__(
        self, message: str = "A database error occurred", details: Optional[dict] = None
    ):
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR, details)


class PredictionException(BaseAppException):
    """General failure in prediction logic."""

    def __init__(
        self, message: str = "Prediction failed", details: Optional[dict] = None
    ):
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR, details)


class ModelNotLoadedException(BaseAppException):
    """Model is not ready or loaded."""

    def __init__(
        self, message: str = "Model not loaded", details: Optional[dict] = None
    ):
        super().__init__(message, status.HTTP_503_SERVICE_UNAVAILABLE, details)


class MetaAPIException(BaseAppException):
    """Meta/Facebook API error."""

    def __init__(self, message: str = "Meta API request failed"):
        super().__init__(message, status.HTTP_502_BAD_GATEWAY)


class GoogleAdsException(BaseAppException):
    """Google Ads API communication error."""

    def __init__(
        self,
        message: str = "Google Ads API request failed",
        status_code: int = status.HTTP_502_BAD_GATEWAY,
        details: Optional[dict] = None,
    ):
        super().__init__(message, status_code, details)


class GoogleAdsAuthException(GoogleAdsException):
    """Google Ads API authentication/authorization error (401, 403)."""

    def __init__(
        self,
        message: str = "Google Ads API authentication failed",
        details: Optional[dict] = None,
    ):
        super().__init__(message, status.HTTP_401_UNAUTHORIZED, details)


class GoogleAdsValidationException(GoogleAdsException):
    """Google Ads API request validation/syntax error (400)."""

    def __init__(
        self,
        message: str = "Google Ads API request validation failed",
        details: Optional[dict] = None,
    ):
        super().__init__(message, status.HTTP_400_BAD_REQUEST, details)


class KeywordServiceException(BaseAppException):
    """General keyword service logic error."""

    def __init__(
        self,
        message: str = "Keyword service processing failed",
        details: Optional[dict] = None,
    ):
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR, details)


class GoogleAutocompleteException(BaseAppException):
    """Google Autocomplete API communication error."""

    def __init__(
        self,
        message: str = "Google Autocomplete API request failed",
        details: Optional[dict] = None,
    ):
        super().__init__(message, status.HTTP_502_BAD_GATEWAY, details)
