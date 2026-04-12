from typing import List, Optional, Literal
from enum import Enum
from pydantic import BaseModel, Field


class ContextCard(BaseModel):
    content: List[str]
    style: Literal["PARAGRAPH_STYLE", "LIST_STYLE"]
    title: str = Field(..., max_length=60)


class QuestionOption(BaseModel):
    key: str
    value: str


class LeadFormQuestion(BaseModel):
    type: str
    label: Optional[str] = None
    key: Optional[str] = None
    options: Optional[List[QuestionOption]] = None


class PrivacyPolicy(BaseModel):
    url: str
    link_text: str

class ThankYouPageButtonType(str, Enum):
    VIEW_WEBSITE = "VIEW_WEBSITE"
    CALL_BUSINESS = "CALL_BUSINESS"



class ThankYouPage(BaseModel):
    title: str
    body: str
    button_text: str
    button_type: ThankYouPageButtonType
    website_url: Optional[str] = None
    country_code: Optional[str] = None
    business_phone_number: Optional[str] = None


class LeadFormPayload(BaseModel):
    name: str = Field(..., max_length=50)
    is_optimized_for_quality: bool
    context_card: ContextCard
    question_page_custom_headline: str
    questions: List[LeadFormQuestion]
    privacy_policy: PrivacyPolicy
    thank_you_page: ThankYouPage