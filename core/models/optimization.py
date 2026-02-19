from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Tuple, get_args, Dict, Any
from datetime import datetime

# Single Source of Truth (SSOT) for recommendation enums and character limits.
# Defined in the core layer to ensure strict consistency between Pydantic
# boundary validation and platform-specific logic in 'adapters'.

AgeRangeType = Literal[
    "AGE_RANGE_18_24",
    "AGE_RANGE_25_34",
    "AGE_RANGE_35_44",
    "AGE_RANGE_45_54",
    "AGE_RANGE_55_64",
    "AGE_RANGE_65_UP",
    "AGE_RANGE_UNDETERMINED",
]
# Derived from Literal to avoid duplication
AGE_RANGE_VALUES: Tuple[str, ...] = get_args(AgeRangeType)

GenderType = Literal["MALE", "FEMALE", "UNDETERMINED"]
GENDER_RANGE_VALUES: Tuple[str, ...] = get_args(GenderType)

KeywordMatchType = Literal["EXACT", "PHRASE", "BROAD"]
MATCH_TYPE_VALUES: Tuple[str, ...] = get_args(KeywordMatchType)

# API Limits
HEADLINE_MAX_LENGTH = 30
DESCRIPTION_MAX_LENGTH = 90
SITELINK_TEXT_MAX_LENGTH = 25
SITELINK_DESCRIPTION_MAX_LENGTH = 35
KEYWORD_MAX_LENGTH = 80
URL_MAX_LENGTH = 2048


class AgeFieldRecommendation(BaseModel):
    ad_group_id: str = Field(..., min_length=1)
    ad_group_name: str = Field(..., min_length=1)
    age_range: AgeRangeType
    recommendation: Literal["ADD", "REMOVE"]
    reason: str
    resource_name: Optional[str] = None
    applied: bool = False


class GenderFieldRecommendation(BaseModel):
    resource_name: Optional[str] = None
    ad_group_id: str = Field(..., min_length=1)
    ad_group_name: str = Field(..., min_length=1)
    gender_type: GenderType
    recommendation: Literal["ADD", "REMOVE"]
    reason: str
    applied: bool = False


class SearchTermAnalysis(BaseModel):
    brand: dict
    configuration: dict
    location: dict
    performance: dict
    strength: Literal["LOW", "MEDIUM", "STRONG"]


class KeywordRecommendation(BaseModel):
    text: str = Field(..., min_length=1, max_length=KEYWORD_MAX_LENGTH)
    match_type: KeywordMatchType
    recommendation: Literal["ADD", "PAUSE"] = "ADD"
    reason: str
    origin: Optional[Literal["SEARCH_TERM", "KEYWORD"]] = None
    metrics: Optional[dict] = None
    analysis: Optional[SearchTermAnalysis] = None
    score: Optional[float] = None
    ad_group_id: Optional[str] = Field(None, min_length=1)
    ad_group_name: Optional[str] = Field(None, min_length=1)
    criterion_id: Optional[str] = Field(None, min_length=1)
    resource_name: Optional[str] = Field(None, min_length=1)
    quality_score: Optional[int] = None
    applied: bool = False


class LocationRecommendation(BaseModel):
    resource_name: Optional[str] = None
    geo_target_constant: str
    location_name: str
    country_code: Optional[str] = None
    location_type: Optional[str] = None
    campaign_id: str
    level: str = "CAMPAIGN"
    recommendation: Literal["ADD", "REMOVE"]
    reason: str
    metrics: dict
    applied: bool = False
    ad_group_id: Optional[str] = None
    negative: Optional[bool] = False


class AddressInfo(BaseModel):
    street_address: Optional[str] = None
    city_name: Optional[str] = None
    postal_code: Optional[str] = None
    country_code: Optional[str] = None


class ProximityRecommendation(BaseModel):
    campaign_id: Optional[str] = None
    ad_group_id: Optional[str] = None
    level: Literal["CAMPAIGN", "AD_GROUP"]
    radius: float
    radius_units: Literal["MILES", "KILOMETERS"]
    address: Optional[AddressInfo] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    recommendation: Literal["ADD", "REMOVE"]
    resource_name: Optional[str] = None
    applied: bool = False


class HeadlineRecommendation(BaseModel):
    ad_group_id: str = Field(..., min_length=1)
    ad_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, max_length=HEADLINE_MAX_LENGTH)
    recommendation: Literal["ADD", "REMOVE"]
    pinned_field: Optional[str] = None
    reason: str
    applied: bool = False


class DescriptionRecommendation(BaseModel):
    ad_group_id: str = Field(..., min_length=1)
    ad_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, max_length=DESCRIPTION_MAX_LENGTH)
    recommendation: Literal["ADD", "REMOVE"]
    pinned_field: Optional[str] = None
    reason: str
    applied: bool = False


class SitelinkRecommendation(BaseModel):
    campaign_id: str = Field(..., min_length=1)
    link_text: str = Field(..., min_length=1, max_length=SITELINK_TEXT_MAX_LENGTH)
    description1: Optional[str] = Field(
        None, max_length=SITELINK_DESCRIPTION_MAX_LENGTH
    )
    description2: Optional[str] = Field(
        None, max_length=SITELINK_DESCRIPTION_MAX_LENGTH
    )
    final_url: str = Field(..., min_length=1, max_length=URL_MAX_LENGTH)
    final_mobile_url: Optional[str] = Field(None, max_length=URL_MAX_LENGTH)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    recommendation: Literal["ADD", "REMOVE", "UPDATE"]
    asset_resource_name: Optional[str] = None  # Reference to the actual Asset
    campaign_asset_resource_name: Optional[str] = None  # Reference to the link
    applied: bool = False


class OptimizationFields(BaseModel):
    age: Optional[List[AgeFieldRecommendation]] = None
    gender: Optional[List[GenderFieldRecommendation]] = None
    keywords: Optional[List[KeywordRecommendation]] = None
    negativeKeywords: Optional[List[KeywordRecommendation]] = None
    locationOptimizations: Optional[List[LocationRecommendation]] = None
    proximityOptimizations: Optional[List[ProximityRecommendation]] = None
    headlines: Optional[List[HeadlineRecommendation]] = None
    descriptions: Optional[List[DescriptionRecommendation]] = None
    sitelinks: Optional[List[SitelinkRecommendation]] = None


class CampaignRecommendation(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    platform: str  # google_ads, meta_ads, tiktok_ads, etc.
    parent_account_id: str = Field(
        ..., min_length=1
    )  # Google: loginCustomerId, Meta: businessId
    account_id: str = Field(..., min_length=1)  # Google: customerId, Meta: adAccountId
    product_id: Optional[str] = None  # Your product (website) linked to campaign
    campaign_id: str = Field(..., min_length=1)
    campaign_name: str
    campaign_type: str
    completed: bool = False
    fields: OptimizationFields


class OptimizationResponse(BaseModel):
    recommendations: List[CampaignRecommendation]


class MutationResponse(BaseModel):
    """Standardized response for mutation operations."""

    success: bool
    message: str
    campaignRecommendation: Optional[CampaignRecommendation] = None
    operations: Optional[List[dict]] = None
    errors: List[str] = []
    details: Optional[Dict[str, Any]] = None
