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
    recommendation: Literal["ADD"] = "ADD"
    reason: str
    source: Literal["SEARCH_TERM"] = "SEARCH_TERM"
    metrics: dict
    analysis: SearchTermAnalysis


class OptimizationFields(BaseModel):
    age: Optional[List[AgeFieldRecommendation]] = None
    keywords: Optional[List[KeywordRecommendation]] = None
    negativeKeywords: Optional[List[KeywordRecommendation]] = None


class CampaignRecommendation(BaseModel):
    platform: str  # google_ads, meta_ads, tiktok_ads, etc.
    parent_account_id: str  # Google: loginCustomerId, Meta: businessId
    account_id: str  # Google: customerId, Meta: adAccountId
    product_id: str  # Your product (website) linked to campaign
    campaign_id: str
    campaign_name: str
    campaign_type: str
    completed: bool = False
    fields: OptimizationFields


class OptimizationResponse(BaseModel):
    recommendations: List[CampaignRecommendation]
