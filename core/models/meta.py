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


class DetailedTargeting(BaseModel):
    interests: List[str] = []
    behaviors: List[str] = []
    demographics: List[str] = []    


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


class LeadFormType(str, Enum):
    MORE_VOLUME = "MORE_VOLUME"
    HIGHER_INTENT = "HIGHER_INTENT"


class DescriptionType(str, Enum):
    PARAGRAPH = "PARAGRAPH"
    LIST = "LIST"


class LeadFormIntroduction(BaseModel):
    headline: str = Field(..., max_length=60)
    description_type: DescriptionType
    paragraph: Optional[str] = None
    list_items: Optional[List[str]] = None

    @model_validator(mode="after")
    def validate_description(self):

        if self.description_type == DescriptionType.PARAGRAPH:
            if not self.paragraph:
                raise ValueError("paragraph required when description_type is PARAGRAPH")

        if self.description_type == DescriptionType.LIST:
            if not self.list_items:
                raise ValueError("list_items required when description_type is LIST")

            if not (2 <= len(self.list_items) <= 5):
                raise ValueError("list_items must contain between 2 and 5 items")

        return self


class LeadFormQuestionCategory(str, Enum):
    CONTACT_FIELDS = "CONTACT_FIELDS"
    USER_INFORMATION = "USER_INFORMATION"
    DEMOGRAPHIC_QUESTIONS = "DEMOGRAPHIC_QUESTIONS"
    WORK_INFORMATION = "WORK_INFORMATION"


class LeadFormQuestion(BaseModel):
    category: LeadFormQuestionCategory
    fields: List[str]


class QuestionType(str, Enum):
    SHORT_ANSWER = "SHORT_ANSWER"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"


class LeadFormCustomQuestion(BaseModel):
    type: QuestionType
    question: str
    options: Optional[List[str]] = None

    @model_validator(mode="after")
    def validate_options(self):

        if self.type == QuestionType.MULTIPLE_CHOICE:
            if not self.options:
                raise ValueError(
                    "MULTIPLE_CHOICE questions must include options"
                )

            if len(self.options) > 5:
                self.options = self.options[:5]

            if len(self.options) < 3:
                raise ValueError(
                    "MULTIPLE_CHOICE questions must have at least 3 options"
                )

        if self.type == QuestionType.SHORT_ANSWER:
            if self.options:
                raise ValueError(
                    "SHORT_ANSWER questions must NOT include options"
                )

        return self


class LeadFormQuestions(BaseModel):
    categories: Optional[List[LeadFormQuestion]] = None
    custom_questions: Optional[List[LeadFormCustomQuestion]] = None


class LeadFormPrivacyPolicy(BaseModel):
    link: Optional[str] = None
    link_text: str = Field(..., max_length=100)


class LeadFormCompletion(BaseModel):
    headline: str
    description: str
    action_type: Literal["GO_TO_WEBSITE", "DOWNLOAD", "CALL_BUSINESS"]
    call_to_action: str
    link: Optional[str] = None
    phone_number: Optional[str] = None

    @model_validator(mode="after")
    def validate_action_type(self):

        if self.action_type in ["GO_TO_WEBSITE", "DOWNLOAD"]:
            if not self.link:
                raise ValueError("link required when action_type is GO_TO_WEBSITE or DOWNLOAD")
            self.phone_number = None

        if self.action_type == "CALL_BUSINESS":
            if not self.phone_number:
                raise ValueError("phone_number required when action_type is CALL_BUSINESS")
            self.link = None

        return self


class LeadFormPayload(BaseModel):
    form_name: str = Field(..., max_length=50)
    form_type: LeadFormType
    introduction: LeadFormIntroduction
    questions: LeadFormQuestions
    privacy_policy: LeadFormPrivacyPolicy
    completion: LeadFormCompletion