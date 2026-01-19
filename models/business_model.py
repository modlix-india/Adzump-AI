from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
from structlog import get_logger    #type: ignore

logger = get_logger(__name__)


class BusinessMetadata(BaseModel):
    brand_name: str = Field(default="Unknown", description="Business brand name")
    business_type: str = Field(default="Unknown", description="Type of business")
    primary_location: str = Field(
        default="Unknown", description="Primary business location"
    )
    service_areas: List[str] = Field(
        default_factory=list, description="Service area locations"
    )
    unique_features: List[str] = Field(
        default_factory=list, description="Unique business features"
    )

    @classmethod
    def from_raw_data(cls, data: dict) -> "BusinessMetadata":
        if not isinstance(data, dict):
            logger.warning(f"Expected dict, got {type(data)}. Using defaults.")
            return cls()

        valid_data = {}

        # String fields
        for field in ["brand_name", "business_type", "primary_location"]:
            value = data.get(field)
            if isinstance(value, str) and value.strip():
                valid_data[field] = value.strip()
            else:
                valid_data[field] = "Unknown"

        # List fields
        for field in ["service_areas", "unique_features"]:
            value = data.get(field)
            if isinstance(value, list):
                valid_data[field] = [
                    item.strip()
                    for item in value
                    if isinstance(item, str) and item.strip()
                ]
            else:
                valid_data[field] = []

        try:
            return cls(**valid_data)
        except Exception as e:
            logger.warning(f"Failed to create BusinessMetadata: {e}. Using defaults.")
            return cls()

    model_config = {
        "json_schema_extra": {
            "example": {
                "brand_name": "Acme Plumbing",
                "business_type": "Plumbing Services",
                "primary_location": "Bangalore",
                "service_areas": ["Koramangala", "Indiranagar", "Whitefield"],
                "unique_features": ["24/7 emergency service", "licensed plumbers"],
            }
        }
    }


class ScreenshotRequest(BaseModel):
    business_url: str
    external_url: Optional[str] = None
    retake: bool = False


class ScreenshotResponse(BaseModel):
    url: str
    storage_id: Optional[str]
    screenshot: Optional[str]

class WebsiteSummaryRequest(BaseModel):
    business_url: str
    external_url: Optional[str] = None
    rescrape: bool = False

class LocationInfo(BaseModel):
    area_location: Optional[str] = None
    product_location: Optional[str] = None
    interested_locations: List[str] = []

class WebsiteSummaryResponse(BaseModel):
    business_url: str
    storage_id: Optional[str] = None
    external_url: Optional[str] = None 
    business_type: Optional[str] = None
    summary: Optional[str] = None
    final_summary: Optional[str] = None
    location: Optional[LocationInfo] = None
    suggested_geo_targets: Optional[List[dict]] = None
    unresolved_locations: Optional[List[str]] = None

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

