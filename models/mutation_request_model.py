from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from core.models.optimization import CampaignRecommendation


class MutationRequest(BaseModel):
    """Request model for executing Google Ads mutations for a single campaign."""

    clientCode: Optional[str] = Field(
        None, description="Client Code for tenant identification"
    )

    campaignRecommendation: CampaignRecommendation = Field(
        ...,
        description="The campaign recommendation object containing changes to apply",
    )

    validateOnly: bool = Field(False, description="If True, validate without executing")
    isPartial: bool = Field(False, description="If True, apply partial changes")


class MutationResponse(BaseModel):
    """Standardized response for mutation operations."""

    success: bool
    message: str
    campaignRecommendation: Optional[CampaignRecommendation] = None
    operations: Optional[List[dict]] = None
    errors: List[str] = []
    details: Optional[Dict[str, Any]] = None
