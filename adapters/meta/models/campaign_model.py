from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class CampaignObjective(str, Enum):
    OUTCOME_LEADS = "OUTCOME_LEADS"
    OUTCOME_TRAFFIC = "OUTCOME_TRAFFIC"
    OUTCOME_AWARENESS = "OUTCOME_AWARENESS"


class SpecialAdCategory(str, Enum):
    HOUSING = "HOUSING"
    EMPLOYMENT = "EMPLOYMENT"
    CREDIT = "CREDIT"
    ISSUES_ELECTIONS_POLITICS = "ISSUES_ELECTIONS_POLITICS"
    NONE = "NONE"


class CampaignPayload(BaseModel):
    name: str
    objective: CampaignObjective
    special_ad_categories: List[SpecialAdCategory] = Field(default_factory=list)
    special_ad_category_country: Optional[List[str]] = None


class CreateCampaignRequest(BaseModel):
    ad_account_id: str = Field(..., alias="adAccountId")
    campaign_payload: CampaignPayload = Field(..., alias="campaignPayload")


class CreateCampaignResponse(BaseModel):
    campaign_id: str = Field(..., alias="campaignId")
