from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field, model_validator, field_validator



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


class GenerateCreativeRequest(BaseModel):
    session_id: str = Field(..., alias="sessionId")


class GenerateCreativeResponse(BaseModel):
    creativePayload: CreativePayload = Field(..., alias="creativePayload")


class CreateCreativeRequest(BaseModel):
    adAccountId: str = Field(..., alias="adAccountId")
    creativePayload: CreativePayload = Field(..., alias="creativePayload")


class CreateCreativeResponse(BaseModel):
    creativeId: str = Field(..., alias="creativeId")
