from enum import Enum
from typing import List, Literal, Optional, Dict, Any, Annotated, Set
from datetime import date, datetime
import re

from pydantic import BaseModel, Field, model_validator, field_validator, ConfigDict
from agents.meta.payload_builders import constants as meta_constants


class CampaignObjective(str, Enum):
    OUTCOME_AWARENESS = "OUTCOME_AWARENESS"
    OUTCOME_TRAFFIC = "OUTCOME_TRAFFIC"
    OUTCOME_ENGAGEMENT = "OUTCOME_ENGAGEMENT"
    OUTCOME_LEADS = "OUTCOME_LEADS"
    OUTCOME_SALES = "OUTCOME_SALES"
    OUTCOME_APP_PROMOTION = "OUTCOME_APP_PROMOTION"


class SpecialAdCategory(str, Enum):
    HOUSING = "HOUSING"
    EMPLOYMENT = "EMPLOYMENT"
    CREDIT = "CREDIT"
    ISSUES_ELECTIONS_POLITICS = "ISSUES_ELECTIONS_POLITICS"
    NONE = "NONE"


class AdCreationStage(str, Enum):
    ASSEMBLY = "ASSEMBLY"
    CAMPAIGN = "CAMPAIGN"
    ADSET = "ADSET"
    CREATIVE = "CREATIVE"
    AD = "AD"


CountryCode = Annotated[
    str, Field(pattern="^[A-Z]{2}$")  # exactly 2 uppercase letters
]


class Status(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class CampaignPayload(BaseModel):
    name: str
    objective: CampaignObjective
    status: Status
    special_ad_categories: Optional[List[SpecialAdCategory]] = None
    special_ad_category_country: Optional[List[CountryCode]] = None


# it should be delete after campaign builder is merged
class CreateCampaignRequest(BaseModel):
    ad_account_id: str = Field(..., alias="adAccountId")
    campaign_payload: CampaignPayload = Field(..., alias="campaignPayload")


# it should be delete after adset builder is merged
class AdSetPayload(BaseModel):
    genders: List[Literal["MALE", "FEMALE"]]
    age_min: int = Field(..., ge=18, le=65)
    age_max: int = Field(..., ge=18, le=65)
    languages: List[str]


# it should be delete after adset builder is merged
class CreateAdSetRequest(BaseModel):
    ad_account_id: str = Field(..., alias="adAccountId", min_length=1)
    campaign_id: str = Field(..., alias="campaignId", min_length=1)
    adset_payload: AdSetPayload = Field(..., alias="adsetPayload")


# it should be delete after creative builder is merged
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
        default=None, description="Base64 image (only for preview / upload step)"
    )
    image_hash: Optional[str] = Field(
        default=None, description="Meta uploaded image hash"
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


# AdSet
class Gender(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class BudgetType(str, Enum):
    DAILY = "DAILY"
    LIFETIME = "LIFETIME"


class OptimizationGoal(str, Enum):
    OFFSITE_CONVERSIONS = "OFFSITE_CONVERSIONS"
    LEADS = "LEADS"
    LINK_CLICKS = "LINK_CLICKS"
    NONE = "NONE"
    APP_INSTALLS = "APP_INSTALLS"
    AD_RECALL_LIFT = "AD_RECALL_LIFT"
    ENGAGED_USERS = "ENGAGED_USERS"
    EVENT_RESPONSES = "EVENT_RESPONSES"
    IMPRESSIONS = "IMPRESSIONS"
    LEAD_GENERATION = "LEAD_GENERATION"
    QUALITY_LEAD = "QUALITY_LEAD"
    PAGE_LIKES = "PAGE_LIKES"
    POST_ENGAGEMENT = "POST_ENGAGEMENT"
    QUALITY_CALL = "QUALITY_CALL"
    REACH = "REACH"
    LANDING_PAGE_VIEWS = "LANDING_PAGE_VIEWS"
    VISIT_INSTAGRAM_PROFILE = "VISIT_INSTAGRAM_PROFILE"
    ENGAGED_PAGE_VIEWS = "ENGAGED_PAGE_VIEWS"
    VALUE = "VALUE"
    THRUPLAY = "THRUPLAY"
    DERIVED_EVENTS = "DERIVED_EVENTS"
    APP_INSTALLS_AND_OFFSITE_CONVERSIONS = "APP_INSTALLS_AND_OFFSITE_CONVERSIONS"
    CONVERSATIONS = "CONVERSATIONS"
    IN_APP_VALUE = "IN_APP_VALUE"
    MESSAGING_PURCHASE_CONVERSION = "MESSAGING_PURCHASE_CONVERSION"
    SUBSCRIBERS = "SUBSCRIBERS"
    REMINDERS_SET = "REMINDERS_SET"
    MEANINGFUL_CALL_ATTEMPT = "MEANINGFUL_CALL_ATTEMPT"
    PROFILE_VISIT = "PROFILE_VISIT"
    PROFILE_AND_PAGE_ENGAGEMENT = "PROFILE_AND_PAGE_ENGAGEMENT"
    ADVERTISER_SILOED_VALUE = "ADVERTISER_SILOED_VALUE"
    AUTOMATIC_OBJECTIVE = "AUTOMATIC_OBJECTIVE"
    MESSAGING_APPOINTMENT_CONVERSION = "MESSAGING_APPOINTMENT_CONVERSION"


# billing_event — what you pay for
class BillingEvent(str, Enum):
    IMPRESSIONS = "IMPRESSIONS"  # pay per 1000 impressions
    CLICKS = "CLICKS"
    APP_INSTALLS = "APP_INSTALLS"
    LINK_CLICKS = "LINK_CLICKS"
    NONE = "NONE"
    OFFER_CLAIMS = "OFFER_CLAIMS"
    PAGE_LIKES = "PAGE_LIKES"
    POST_ENGAGEMENT = "POST_ENGAGEMENT"
    THRUPLAY = "THRUPLAY"
    PURCHASE = "PURCHASE"
    LISTING_INTERACTION = "LISTING_INTERACTION"


class BidStrategy(str, Enum):
    LOWEST_COST_WITHOUT_CAP = "LOWEST_COST_WITHOUT_CAP"
    LOWEST_COST_WITH_BID_CAP = "LOWEST_COST_WITH_BID_CAP"
    LOWEST_COST_WITH_MIN_ROAS = "LOWEST_COST_WITH_MIN_ROAS"
    COST_CAP = "COST_CAP"
    TARGET_COST = "TARGET_COST"


class DestinationType(str, Enum):
    WEBSITE = "WEBSITE"
    APP = "APP"
    MESSENGER = "MESSENGER"
    ON_AD = "ON_AD"
    ON_POST = "ON_POST"
    ON_VIDEO = "ON_VIDEO"
    ON_PAGE = "ON_PAGE"
    ON_EVENT = "ON_EVENT"
    WHATSAPP = "WHATSAPP"
    IMAGINE = "IMAGINE"
    FACEBOOK = "FACEBOOK"
    FACEBOOK_LIVE = "FACEBOOK_LIVE"
    SHOP_AUTOMATIC = "SHOP_AUTOMATIC"
    INSTAGRAM_LIVE = "INSTAGRAM_LIVE"
    FACEBOOK_PAGE = "FACEBOOK_PAGE"
    INSTAGRAM_DIRECT = "INSTAGRAM_DIRECT"
    INSTAGRAM_PROFILE = "INSTAGRAM_PROFILE"
    APPLINKS_AUTOMATIC = "APPLINKS_AUTOMATIC"
    INSTAGRAM_PROFILE_AND_FACEBOOK_PAGE = "INSTAGRAM_PROFILE_AND_FACEBOOK_PAGE"
    MESSAGING_MESSENGER_WHATSAPP = "MESSAGING_MESSENGER_WHATSAPP"
    MESSAGING_INSTAGRAM_DIRECT_MESSENGER = "MESSAGING_INSTAGRAM_DIRECT_MESSENGER"
    MESSAGING_INSTAGRAM_DIRECT_MESSENGER_WHATSAPP = (
        "MESSAGING_INSTAGRAM_DIRECT_MESSENGER_WHATSAPP"
    )
    MESSAGING_INSTAGRAM_DIRECT_WHATSAPP = "MESSAGING_INSTAGRAM_DIRECT_WHATSAPP"


# Promoted Object
class PromotedObjectType(str, Enum):
    PIXEL = "PIXEL"
    APP = "APP"
    PAGE = "PAGE"


HeadlineStr = Annotated[str, Field(max_length=meta_constants.MAX_HEADLINE_CHARS)]
PrimaryTextStr = Annotated[str, Field(max_length=meta_constants.MAX_PRIMARY_TEXT_CHARS)]
DescriptionStr = Annotated[str, Field(max_length=meta_constants.MAX_DESCRIPTION_CHARS)]


class ConversionEvent(str, Enum):
    LEAD = "LEAD"
    PURCHASE = "PURCHASE"
    ADD_TO_CART = "ADD_TO_CART"
    INITIATED_CHECKOUT = "INITIATED_CHECKOUT"
    ADD_PAYMENT_INFO = "ADD_PAYMENT_INFO"
    COMPLETE_REGISTRATION = "COMPLETE_REGISTRATION"
    SEARCH = "SEARCH"
    VIEW_CONTENT = "VIEW_CONTENT"
    SUBSCRIBE = "SUBSCRIBE"
    CONTACT = "CONTACT"


# Creative
class CreativeType(str, Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"


class CreativeFormat(str, Enum):
    AUTOMATIC_FORMAT = "AUTOMATIC_FORMAT"
    CAROUSEL = "CAROUSEL"
    CAROUSEL_IMAGE = "CAROUSEL_IMAGE"
    CAROUSEL_VIDEO = "CAROUSEL_VIDEO"
    COLLECTION = "COLLECTION"
    SINGLE_IMAGE = "SINGLE_IMAGE"
    SINGLE_VIDEO = "SINGLE_VIDEO"
    POST = "POST"


class NonDemographicType(str, Enum):
    interests = "interests"
    behaviors = "behaviors"


# MODELS


# Existing IDs
class ExistingIdsPayload(BaseModel):
    campaign_id: Optional[str] = None
    adset_id: Optional[str] = None
    creative_id: Optional[str] = None
    ad_id: Optional[str] = None


# Ad
class AdPayload(BaseModel):
    name: str
    status: Status
    adset_id: Optional[str] = None
    creative: Optional[Dict[str, Annotated[str, Field(min_length=1)]]] = (
        None  # creative_id: str
    )


# Schedule
class Schedule(BaseModel):
    start_time: date
    end_time: Optional[date] = None

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def parse_date(cls, value):
        if not value:
            return value
        if isinstance(value, str):
            try:
                parsed = datetime.strptime(value, "%d/%m/%Y").date()
                return parsed.isoformat()
            except Exception:
                raise ValueError("Date must be in format dd/mm/yyyy")

        return value

    @model_validator(mode="after")
    def validate_dates(self):
        current_date = datetime.now().date()
        if self.start_time < current_date:
            raise ValueError("start_time cannot be in the past")

        if self.end_time and self.end_time < self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class Locale(BaseModel):
    key: int
    name: str


class Location(BaseModel):
    key: str
    name: str
    type: str
    radius: Optional[int] = None
    distance_unit: Optional[str] = None


class TargetingEntity(BaseModel):
    id: str
    name: str
    type: str
    model_config = ConfigDict(extra="allow")


# Targeting (Flexible)
class Targeting(BaseModel):
    locations: list[Location]

    locales: Optional[list[Locale]] = None
    behaviors: Optional[list[TargetingEntity]] = None
    interests: Optional[list[TargetingEntity]] = None
    demographics: Optional[list[TargetingEntity]] = None

    age_min: Optional[int] = Field(None, ge=18, le=65)
    age_max: Optional[int] = Field(None, ge=18, le=65)
    genders: Optional[list[Gender]] = None

    @field_validator("locations")
    @classmethod
    def validate_locations(cls, v):
        if not v:
            raise ValueError("At least one location is required")
        return v

    @model_validator(mode="after")
    @classmethod
    def validate_targeting(cls, values):
        interests = getattr(values, "interests", []) or []
        behaviors = getattr(values, "behaviors", []) or []
        demographics = getattr(values, "demographics", []) or []

        # Validate type of interests and behaviors
        for i in interests:
            if i.type != NonDemographicType.interests:
                raise ValueError(f"Invalid type '{i.type}' in interests")

        for b in behaviors:
            if b.type != NonDemographicType.behaviors:
                raise ValueError(f"Invalid type '{b.type}' in behaviors")

        # Validate demographics do not contain interests/behaviors
        for d in demographics:
            if d.type in NonDemographicType.__members__:
                raise ValueError(f"Invalid type '{d.type}' in demographics")

        # Deduplicate IDs across all groups
        seen_ids: Set[str] = set()
        for group in [interests, behaviors, demographics]:
            for e in group:
                if e.id in seen_ids:
                    raise ValueError(
                        f"Duplicate targeting id '{e.id}' found across groups"
                    )
                seen_ids.add(e.id)

        return values


# Budget
class Budget(BaseModel):
    amount: int = Field(..., gt=100)
    type: BudgetType

    def to_meta_payload(self) -> dict:
        minor_units = int(self.amount * meta_constants.INR_TO_MINOR_UNIT)
        key = "daily_budget" if self.type == BudgetType.DAILY else "lifetime_budget"
        return {key: minor_units}


# Bidding
class Bidding(BaseModel):
    optimization_goal: OptimizationGoal
    billing_event: BillingEvent
    bid_strategy: BidStrategy
    bid_amount: Optional[int] = None

    @model_validator(mode="after")
    def validate_bid_amount(self):
        if (
            self.bid_strategy.value
            in meta_constants.BID_STRATEGIES_REQUIRING_BID_AMOUNT
            and self.bid_amount is None
        ):
            raise ValueError(
                f"bid_amount is required for bid_strategy '{self.bid_strategy.value}'"
            )
        return self


# Promoted Object
class PromotedObject(BaseModel):
    type: PromotedObjectType

    pixel_id: Optional[str] = Field(default=None, min_length=1)
    event: Optional[ConversionEvent] = None
    application_id: Optional[str] = Field(default=None, min_length=1)
    object_store_url: Optional[str] = Field(default=None, min_length=1)
    page_id: Optional[str] = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_required_fields(self):
        if self.type == PromotedObjectType.PIXEL:
            if not self.pixel_id:
                raise ValueError("pixel_id is required for PIXEL type")
            if not self.event:
                raise ValueError("event is required for PIXEL type")

        elif self.type == PromotedObjectType.APP:
            if not self.application_id:
                raise ValueError("application_id is required for APP type")
            if not self.object_store_url:
                raise ValueError("object_store_url is required for APP type")

        elif self.type == PromotedObjectType.PAGE:
            if not self.page_id:
                raise ValueError("page_id is required for PAGE type")

        return self

    def to_meta_payload(self) -> dict:
        if self.type == PromotedObjectType.PAGE:
            return {"page_id": str(self.page_id)}

        elif self.type == PromotedObjectType.PIXEL:
            return {
                "pixel_id": str(self.pixel_id),
                "custom_event_type": self.event.value if self.event else None,
            }

        elif self.type == PromotedObjectType.APP:
            return {
                "application_id": str(self.application_id),
                "object_store_url": self.object_store_url,
            }

        return {}


# AdSet
class AdSetPayload(BaseModel):
    name: str
    status: Status

    schedule: Optional[Schedule] = None
    targeting: Targeting

    destination_type: DestinationType

    budget: Budget
    bidding: Bidding
    promoted_object: PromotedObject
    campaign_id: Optional[str] = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_lifetime_budget_requires_schedule(self):
        if self.budget.type == BudgetType.LIFETIME:
            if self.schedule is None:
                raise ValueError("schedule is required when using a LIFETIME budget")
            if self.schedule.end_time is None:
                raise ValueError(
                    "end_time is required in schedule when using a LIFETIME budget"
                )
        return self


# Creative models
class WebsiteCTA(BaseModel):
    type: CallToAction
    url: str
    lead_gen_form_id: None = None  # not allowed


class LeadGenCTA(BaseModel):
    type: CallToAction
    lead_gen_form_id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)


# BASE CREATIVE
class BaseCreative(BaseModel):
    name: str
    type: CreativeType
    page_id: str = Field(..., min_length=1)
    instagram_user_id: Optional[str] = Field(default=None, min_length=1)
    destination_type: DestinationType
    image_hashes: List[str] = Field(
        ..., min_length=1, max_length=meta_constants.MAX_IMAGES
    )

    headlines: List[HeadlineStr] = Field(
        ..., min_length=1, max_length=meta_constants.MAX_HEADLINES
    )

    primary_texts: List[PrimaryTextStr] = Field(
        ..., min_length=1, max_length=meta_constants.MAX_PRIMARY_TEXTS
    )

    descriptions: Optional[List[DescriptionStr]] = Field(
        default=None, min_length=1, max_length=meta_constants.MAX_DESCRIPTIONS
    )


class WebsiteCreative(BaseCreative):
    destination_type: Literal[DestinationType.WEBSITE]
    call_to_action: WebsiteCTA
    url_tags: Optional[str] = None

    @field_validator("url_tags", mode="before")
    @classmethod
    def validate_url_tags(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return value

        value = value.strip()
        valid_keys = meta_constants.VALID_UTM_KEYS
        valid_macros = meta_constants.VALID_META_MACROS

        for pair in value.split("&"):
            if not pair:
                continue
            if "=" not in pair:
                raise ValueError(
                    f"Invalid url_tags format: '{pair}' is not a key=value pair"
                )
            key, val = pair.split("=", 1)
            key = key.strip()
            val = val.strip()

            if key not in valid_keys:
                raise ValueError(
                    f"Unknown url_tag key '{key}'. Allowed keys: {sorted(valid_keys)}"
                )
            if not val:
                raise ValueError(f"url_tag key '{key}' has an empty value")

            # Validate any {{macro}} tokens found in the value
            macros_in_val = re.findall(r"\{\{[^}]+\}\}", val)
            for macro in macros_in_val:
                if macro not in valid_macros:
                    raise ValueError(
                        f"Unknown Meta macro '{macro}' in url_tag '{key}'. "
                        f"Allowed macros: {sorted(valid_macros)}"
                    )

        return value


class LeadGenCreative(BaseCreative):
    destination_type: Literal[DestinationType.ON_AD]
    call_to_action: LeadGenCTA


# FINAL CREATIVE PAYLOAD (UNION)

CreativePayload = Annotated[
    WebsiteCreative | LeadGenCreative,
    Field(discriminator="destination_type"),
]


class AssembledMetaPayloads(BaseModel):
    campaign_payload: Dict[str, Any]
    adset_payload: Dict[str, Any]
    creative_payload: Dict[str, Any]
    ad_payload: Dict[str, Any]


# Root Request
class CreateMetaAdRequest(BaseModel):
    ad_account_id: str = Field(..., min_length=1)

    campaign: CampaignPayload
    adset: AdSetPayload
    creative: CreativePayload

    ad: AdPayload

    existing_ids: ExistingIdsPayload


# Detailed Targeting Enums
class TargetingCategory(str, Enum):
    INTERESTS = "interests"
    DEMOGRAPHICS = "demographics"
    BEHAVIORS = "behaviors"


# LLM response models
class TargetingSeedsResponse(BaseModel):
    """Parsed LLM response for seed generation."""

    seeds: List[str]


class TargetingFilterResponse(BaseModel):
    """Parsed LLM response for candidate filtering."""

    selected_ids: List[str]


# Per-category output
class CategoryTargetingResult(BaseModel):
    """Filtered targeting results for a single category."""

    category: str
    items: List[TargetingEntity]


# Final agent output
class MetaTargetingSuggestionResult(BaseModel):
    """Complete output returned by the orchestrator."""

    interests: List[TargetingEntity] = []
    demographics: List[TargetingEntity] = []
    behaviours: List[TargetingEntity] = []
