from pydantic import BaseModel
from typing import List, Optional, Literal


class AgeFieldRecommendation(BaseModel):
    ad_group_id: str
    ad_group_name: str
    age_range: str
    recommendation: Literal["ADD", "REMOVE"]
    reason: str


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


class OptimizationFields(BaseModel):
    age: Optional[List[AgeFieldRecommendation]] = None
    assets: Optional[List["AssetFieldRecommendation"]] = None
    keywords: Optional[List[KeywordRecommendation]] = None
    negativeKeywords: Optional[List[KeywordRecommendation]] = None
    locationOptimizations: Optional[List[LocationRecommendation]] = None


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


class AssetFieldRecommendation(BaseModel):
    ad_group_id: str
    ad_group_name: str
    ad_id: str
    ad_name: str
    ad_group_ad_asset_resource_name: str
    asset_id: Optional[str] = None
    asset_type: Literal["HEADLINE", "DESCRIPTION"]
    text: str
    recommendation: Literal["ADD", "REMOVE"]
    reason: str
    applied: bool = False
