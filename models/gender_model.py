from pydantic import BaseModel
from typing import List, Optional

class OptimizedGenderGroup(BaseModel):
    gender: str
    ctr: Optional[float] = None
    averageCpc: Optional[float] = None
    costPerConversion: Optional[float] = None
    recommendation: str
    reason: str
    is_optimized: bool
 
class AdGroupGenderOptimization(BaseModel):
    ad_group_id: str
    ad_group_name: str
    optimized_genders: List[OptimizedGenderGroup]
    rationale_summary: str

class CampaignGenderOptimization(BaseModel):
    campaign_id: str
    campaign_name: str
    ad_groups: List[AdGroupGenderOptimization]

class GenderOptimizationResponse(BaseModel):
    campaigns: List[CampaignGenderOptimization]