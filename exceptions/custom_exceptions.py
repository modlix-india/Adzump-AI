from fastapi import status

class BaseAppException(Exception):
    """Base class for all app-specific exceptions."""
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        self.message = message
        self.status_code = status_code
        super().__init__(message)

class BusinessValidationException(BaseAppException):
    """Invalid input or business rule violation."""
    def __init__(self, message: str):
        super().__init__(message, status.HTTP_422_UNPROCESSABLE_ENTITY)

class AIProcessingException(BaseAppException):
    """OpenAI or AI processing failure."""
    def __init__(self, message: str = "AI model processing failed"):
        super().__init__(message, status.HTTP_502_BAD_GATEWAY)

class ScraperException(BaseAppException):
    """Website scraping failed."""
    def __init__(
        self, 
        message: str = "Failed to scrape website content",
        details: dict = None
    ):
        super().__init__(message, status.HTTP_400_BAD_REQUEST)
        self.details = details or {}

class StorageException(BaseAppException):
    """Storage read/write failed."""
    def __init__(self, message: str = "Error communicating with storage service"):
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR)

class InternalServerException(BaseAppException):
    """Unexpected error in backend logic."""
    def __init__(self, message: str = "Internal server error"):
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR)

class DatabaseException(BaseAppException):
    """Database operation failed."""
    def __init__(self, message: str = "A database error occurred"):
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR)