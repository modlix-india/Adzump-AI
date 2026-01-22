from typing import Optional
from fastapi import status

class BaseAppException(Exception):
    """Base class for all app-specific exceptions."""
    def __init__(
        self, 
        message: str, 
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Optional[dict] = None
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
    def __init__(self, message: str = "AI model processing failed", details: Optional[dict] = None):
        super().__init__(message, status.HTTP_502_BAD_GATEWAY, details)

class ScraperException(BaseAppException):
    """Website scraping failed."""
    def __init__(self,message: str = "Failed to scrape website content",details: Optional[dict] = None):
        super().__init__(message, status.HTTP_502_BAD_GATEWAY, details)

class StorageException(BaseAppException):
    """Storage read/write failed."""
    def __init__(self, message: str = "Error communicating with storage service", details: Optional[dict] = None):
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR, details)

class InternalServerException(BaseAppException):
    """Unexpected error in backend logic."""
    def __init__(self, message: str = "Internal server error", details: Optional[dict] = None):
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR, details)

class DatabaseException(BaseAppException):
    """Database operation failed."""
    def __init__(self, message: str = "A database error occurred", details: Optional[dict] = None):
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR, details)