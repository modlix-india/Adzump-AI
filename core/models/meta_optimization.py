from typing import Literal, Optional, List, Dict, Any
from core.models.optimization import BaseCampaignRecommendation
from pydantic import BaseModel


class MetaAgeFieldRecommendation(BaseModel):
    adset_id: str
    adset_name: str
    current_min: int
    current_max: int
    recommended_min: int
    recommended_max: int
    action: str = "UPDATE_AGE_RANGE"
    reason: str
    applied: bool = False


class MetaOptimizationFields(BaseModel):
    age: Optional[List[MetaAgeFieldRecommendation]] = None


class MetaCampaignRecommendation(BaseCampaignRecommendation):
    """Meta Ads campaign recommendation."""

    platform: Literal["META"] = "META"
    fields: MetaOptimizationFields


class MetaOptimizationResponse(BaseModel):
    success: bool
    message: str
    recommendations: List[MetaCampaignRecommendation] = []
    errors: List[Dict[str, Any]] = []


class MetaAgeAIResponse(BaseModel):
    """The strict schema the AI must follow for recommendations."""

    recommended_age_min: int
    recommended_age_max: int
    reason: str


class AdsetAnalysisResult(BaseModel):
    """Refined internal model to bridge AI results into our grouping logic."""

    account_id: str
    campaign_id: str
    campaign_name: str
    campaign_objective: str
    product_id: Optional[str] = None
    adset_id: str
    adset_name: str
    current_min: int
    current_max: int
    recommended_min: int
    recommended_max: int
    reason: str
