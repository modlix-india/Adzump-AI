from enum import Enum
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, model_validator

import structlog

logger = structlog.get_logger()


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
                logger.warning(
                    "Truncating options from %d to 5", len(self.options)
                )
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
    link_text: Optional[str] = Field(None, max_length=100)


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