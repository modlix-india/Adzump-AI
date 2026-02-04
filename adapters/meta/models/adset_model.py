from typing import List, Dict
from pydantic import BaseModel, Field
from enum import Enum


class Gender(str, Enum):
    ALL = "ALL"
    MALE = "MALE"
    FEMALE = "FEMALE"


class AgeRange(BaseModel):
    min: int = Field(..., ge=18)
    max: int = Field(..., le=65)


class DetailedTargeting(BaseModel):
    interests: List[str] = Field(default_factory=list)
    behaviours: List[str] = Field(default_factory=list)
    demographics: List[str] = Field(default_factory=list)


class AdSetSuggestion(BaseModel):
    adset_name: str
    gender: Gender
    age_range: AgeRange
    daily_budget: int
    languages: List[str] = Field(default_factory=list)
    detailed_targeting: DetailedTargeting


class GenerateAdSetResponse(BaseModel):
    adset_name: str
    human_targeting: AdSetSuggestion
    meta_targeting: Dict


class MetaAdSetPayload(BaseModel):
    adset_name: str
    targeting: Dict
    daily_budget: int | None = None


class CreateAdSetRequest(BaseModel):
    ad_account_id: str = Field(..., alias="adAccountId")
    campaign_id: str = Field(..., alias="campaignId")
    adset_payload: MetaAdSetPayload = Field(..., alias="adsetPayload")


class CreateAdSetResponse(BaseModel):
    adset_id: str = Field(..., alias="adsetId")
