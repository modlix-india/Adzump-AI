from pydantic import BaseModel, Field
from typing import List


class AdSetSuggestion(BaseModel):
    genders: List[int]
    age_min: int
    age_max: int
    locales: List[int]

class CreateAdSetRequest(BaseModel):
    ad_account_id: str = Field(..., alias="adAccountId")
    campaign_id: str = Field(..., alias="campaignId")
    adset_payload: dict = Field(..., alias="adsetPayload")


class CreateAdSetResponse(BaseModel):
    adset_id: str = Field(..., alias="adsetId")
