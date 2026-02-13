from pydantic import BaseModel
from typing import List, Optional, Literal
from datetime import datetime


class AgeFieldRecommendation(BaseModel):
    ad_group_id: str
    ad_group_name: str
    age_range: str
    recommendation: Literal["ADD", "REMOVE"]
    reason: str
    applied: bool = False


class GenderFieldRecommendation(BaseModel):
    ad_group_id: str
    ad_group_name: str
    gender_type: str
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
    text: str
    match_type: str
    recommendation: Literal["ADD", "PAUSE"] = "ADD"
    reason: str
    origin: Optional[Literal["SEARCH_TERM", "KEYWORD"]] = None
    metrics: Optional[dict] = None
    analysis: Optional[SearchTermAnalysis] = None
    score: Optional[float] = None
    ad_group_id: Optional[str] = None
    ad_group_name: Optional[str] = None
    criterion_id: Optional[str] = None
    resource_name: Optional[str] = None
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
    ad_group_id: str
    ad_id: str
    text: str
    recommendation: Literal["ADD", "REMOVE"]
    pinned_field: Optional[str] = None
    reason: str
    applied: bool = False


class DescriptionRecommendation(BaseModel):
    ad_group_id: str
    ad_id: str
    text: str
    recommendation: Literal["ADD", "REMOVE"]
    pinned_field: Optional[str] = None
    reason: str
    applied: bool = False


class SitelinkRecommendation(BaseModel):
    campaign_id: str
    link_text: str
    description1: Optional[str] = None
    description2: Optional[str] = None
    final_url: str
    final_mobile_url: Optional[str] = None
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
    platform: str  # google_ads, meta_ads, tiktok_ads, etc.
    parent_account_id: str  # Google: loginCustomerId, Meta: businessId
    account_id: str  # Google: customerId, Meta: adAccountId
    product_id: Optional[str] = None  # Your product (website) linked to campaign
    campaign_id: str
    campaign_name: str
    campaign_type: str
    completed: bool = False
    fields: OptimizationFields


class OptimizationResponse(BaseModel):
    recommendations: List[CampaignRecommendation]
