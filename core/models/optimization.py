from pydantic import BaseModel
from typing import List, Optional, Literal


class AgeFieldRecommendation(BaseModel):
    ad_group_id: str
    ad_group_name: str
    age_range: str
    recommendation: Literal["ADD", "REMOVE"]
    reason: str


class OptimizationFields(BaseModel):
    age: Optional[List[AgeFieldRecommendation]] = None
    # Future: gender, device, location, etc.


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


class AgeOptimizationResponse(BaseModel):
    recommendations: List[CampaignRecommendation]
