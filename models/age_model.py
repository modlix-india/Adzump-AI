from pydantic import BaseModel
from typing import List, Optional

class OptimizedAgeGroup(BaseModel):
    age_range: str
    ctr: Optional[float] = None
    averageCpc: Optional[float] = None
    costPerConversion: Optional[float] = None
    recommendation: str
    reason: str
    is_optimized: bool

class AdGroupAgeOptimization(BaseModel):
    ad_group_id: str
    ad_group_name: str
    optimized_age_groups: List[OptimizedAgeGroup]
    rationale_summary: str

class CampaignAgeOptimization(BaseModel):
    campaign_id: str
    campaign_name: str
    ad_groups: List[AdGroupAgeOptimization]

class AgeOptimizationResponse(BaseModel):
    campaigns: List[CampaignAgeOptimization]
