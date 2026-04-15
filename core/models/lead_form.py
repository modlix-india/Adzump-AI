from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field


class ContextCardStyle(str, Enum):
    PARAGRAPH_STYLE = "PARAGRAPH_STYLE"
    LIST_STYLE = "LIST_STYLE"


class QuestionType(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    FULL_NAME = "FULL_NAME"
    FIRST_NAME = "FIRST_NAME"
    LAST_NAME = "LAST_NAME"
    CITY = "CITY"
    COUNTRY = "COUNTRY"
    COMPANY_NAME = "COMPANY_NAME"
    JOB_TITLE = "JOB_TITLE"
    MARITIAL_STATUS = "MARITIAL_STATUS"
    CUSTOM = "CUSTOM"


class ThankYouPageButtonType(str, Enum):
    VIEW_WEBSITE = "VIEW_WEBSITE"
    CALL_BUSINESS = "CALL_BUSINESS"


class ContextCard(BaseModel):
    title: str = Field(..., min_length=1, max_length=60)
    content: list[str] = Field(..., min_length=1)
    style: ContextCardStyle


class QuestionOption(BaseModel):
    key: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)


class LeadFormQuestion(BaseModel):
    type: QuestionType
    label: str | None = Field(None, min_length=1)
    key: str | None = Field(None, min_length=1)
    options: list[QuestionOption] | None = None


class PrivacyPolicy(BaseModel):
    url: str = Field(..., min_length=1)
    link_text: str = Field(..., min_length=1)


class ThankYouPage(BaseModel):
    title: str = Field(..., min_length=1, max_length=60)
    body: str = Field(..., min_length=1)
    button_text: str = Field(..., min_length=1)
    button_type: ThankYouPageButtonType
    website_url: Optional[str] = None
    country_code: Optional[str] = None
    business_phone_number: Optional[str] = None


class LeadFormPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    is_optimized_for_quality: bool
    context_card: ContextCard
    question_page_custom_headline: str = Field(..., min_length=1)
    questions: list[LeadFormQuestion] = Field(..., min_length=1)
    privacy_policy: PrivacyPolicy
    thank_you_page: ThankYouPage
    enable_otp_verification: Optional[bool] = False
