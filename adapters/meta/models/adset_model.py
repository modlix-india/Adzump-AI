from pydantic import BaseModel, Field
from typing import List


class AdSetSuggestion(BaseModel):
    genders: List[str]
    age_min: int
    age_max: int
    languages: List[str]

class CreateAdSetRequest(BaseModel):
    ad_account_id: str = Field(..., alias="adAccountId")
    campaign_id: str = Field(..., alias="campaignId")
    adset_payload: dict = Field(..., alias="adsetPayload")


class CreateAdSetResponse(BaseModel):
    adset_id: str = Field(..., alias="adsetId")
