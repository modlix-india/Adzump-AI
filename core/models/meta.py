from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator, field_validator


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


class AdSetPayload(BaseModel):
    genders: List[Literal["MALE", "FEMALE"]]
    age_min: int = Field(..., ge=18, le=65)
    age_max: int = Field(..., ge=18, le=65)
    languages: List[str]


class CreateAdSetRequest(BaseModel):
    ad_account_id: str = Field(..., alias="adAccountId")
    campaign_id: str = Field(..., alias="campaignId")
    adset_payload: AdSetPayload = Field(..., alias="adsetPayload")


class CallToAction(str, Enum):
    APPLY_NOW = "APPLY_NOW"
    BOOK_NOW = "BOOK_NOW"
    BUY_TICKETS = "BUY_TICKETS"
    CONTACT_US = "CONTACT_US"
    DOWNLOAD = "DOWNLOAD"
    GET_OFFER = "GET_OFFER"
    GET_QUOTE = "GET_QUOTE"
    GET_SHOWTIMES = "GET_SHOWTIMES"
    LEARN_MORE = "LEARN_MORE"
    LISTEN_NOW = "LISTEN_NOW"
    ORDER_NOW = "ORDER_NOW"
    PLAY_GAME = "PLAY_GAME"
    REQUEST_TIME = "REQUEST_TIME"
    SEE_MENU = "SEE_MENU"
    SHOP_NOW = "SHOP_NOW"
    SIGN_UP = "SIGN_UP"
    SUBSCRIBE = "SUBSCRIBE"
    WATCH_MORE = "WATCH_MORE"


class CreativeText(BaseModel):
    primary_texts: List[str]
    headlines: List[str]
    descriptions: List[str]
    cta: CallToAction

    @field_validator("primary_texts", "headlines", "descriptions")
    @classmethod
    def validate_exactly_five(cls, value):
        if len(value) != 5:
            raise ValueError("Must contain exactly 5 items")
        return value


class CreativeImage(BaseModel):
    image_url: Optional[str] = Field(
        default=None,
        description="Base64 image (only for preview / upload step)"
    )
    image_hash: Optional[str] = Field(
        default=None,
        description="Meta uploaded image hash"
    )

    @model_validator(mode="after")
    def validate_image_source(self):
        if not self.image_url and not self.image_hash:
            raise ValueError("Either image_url or image_hash must be provided")
        return self


class CreativePayload(BaseModel):
    text: CreativeText
    image: Optional[CreativeImage] = None


class CreateCreativeRequest(BaseModel):
    adAccountId: str = Field(..., alias="adAccountId")
    creativePayload: CreativePayload = Field(..., alias="creativePayload")


class CreateCreativeResponse(BaseModel):
    creativeId: str = Field(..., alias="creativeId")
