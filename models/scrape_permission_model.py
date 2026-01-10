from pydantic import BaseModel
from typing import Optional
from enum import Enum


class WarningType(str, Enum):
    """Types of warnings that allow scraping but notify the user."""
    ROBOTS_TXT = "robots_txt_disallow"
    META_NOINDEX = "meta_robots_noindex"
    META_NOFOLLOW = "meta_robots_nofollow"


class BlockReason(str, Enum):
    """Reasons why scraping was blocked (content actually inaccessible)."""
    HTTP_FORBIDDEN = "http_403_forbidden"
    RATE_LIMITED = "http_429_rate_limited"
    SERVICE_UNAVAILABLE = "http_503_unavailable"
    CAPTCHA_REQUIRED = "captcha_required"
    BOT_PROTECTION = "bot_protection_detected"
    EMPTY_CONTENT = "empty_or_blocked_content"
    TIMEOUT = "request_timeout"
    CONNECTION_ERROR = "connection_error"


class ScrapeWarning(BaseModel):
    """A warning about scraping restrictions (scraping still proceeds)."""
    type: WarningType
    message: str


class ScrapeError(BaseModel):
    """An error that blocks scraping (content inaccessible)."""
    type: BlockReason
    message: str


class ScrapeResult(BaseModel):
    """Result of a scrape operation with warnings and/or errors."""
    success: bool
    url: str
    warnings: list[ScrapeWarning] = []
    error: Optional[ScrapeError] = None
    data: Optional[dict] = None
