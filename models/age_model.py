# TODO: Remove this file - replaced by core/models/optimization.py
from pydantic import BaseModel
from typing import List, Optional


class OptimizedAgeGroup(BaseModel):
    age_range: str
    CPA: Optional[float] = None
    CTR: Optional[float] = None
    CPC: Optional[float] = None
    recommendation: str
    reason: str
    is_optimized: bool


class AdGroupOptimization(BaseModel):
    ad_group_id: str
    ad_group_name: str
    optimized_age_groups: List[OptimizedAgeGroup]
    rationale_summary: str


class CampaignOptimization(BaseModel):
    campaign_id: str
    campaign_name: str
    ad_groups: List[AdGroupOptimization]


class AgeOptimizationResponse(BaseModel):
    campaigns: List[CampaignOptimization]
