from __future__ import annotations
from enum import Enum
from typing import Literal, Any, Annotated
from datetime import date, datetime
import re

from pydantic import (
    BaseModel,
    Field,
    model_validator,
    field_validator,
    ConfigDict,
    computed_field,
)
from core.models import meta_constants


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
    FINANCIAL_PRODUCTS_SERVICES = "FINANCIAL_PRODUCTS_SERVICES"
    ISSUES_ELECTIONS_POLITICS = "ISSUES_ELECTIONS_POLITICS"
    NONE = "NONE"


class AdCreationStage(str, Enum):
    ASSEMBLY = "ASSEMBLY"
    CAMPAIGN = "CAMPAIGN"
    ADSET = "ADSET"
    CREATIVE = "CREATIVE"
    AD = "AD"


class Status(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


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


class BillingEvent(str, Enum):
    IMPRESSIONS = "IMPRESSIONS"
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
    """
    Meta Bid Strategies.
    SOURCE_LINK = "https://developers.facebook.com/docs/marketing-api/bidding/overview/bid-strategy"
    """

    LOWEST_COST_WITHOUT_CAP = "LOWEST_COST_WITHOUT_CAP"
    LOWEST_COST_WITH_BID_CAP = "LOWEST_COST_WITH_BID_CAP"
    LOWEST_COST_WITH_MIN_ROAS = "LOWEST_COST_WITH_MIN_ROAS"
    COST_CAP = "COST_CAP"

    @property
    def requires_bid_amount(self) -> bool:
        """Return True if the strategy requires the 'bid_amount' field."""
        return self in {
            BidStrategy.LOWEST_COST_WITH_BID_CAP,
            BidStrategy.COST_CAP,
        }


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


class PromotedObjectType(str, Enum):
    PIXEL = "PIXEL"
    APP = "APP"
    PAGE = "PAGE"


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


class CreativeType(str, Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    CAROUSEL = "CAROUSEL"


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


CountryCode = Annotated[str, Field(pattern="^[A-Z]{2}$")]
HeadlineStr = Annotated[str, Field(max_length=meta_constants.MAX_HEADLINE_CHARS)]
PrimaryTextStr = Annotated[str, Field(max_length=meta_constants.MAX_PRIMARY_TEXT_CHARS)]
DescriptionStr = Annotated[str, Field(max_length=meta_constants.MAX_DESCRIPTION_CHARS)]

# Discriminated Union for Creative types
CreativePayload = Annotated[
    "WebsiteCreative | LeadGenCreative", Field(discriminator="destination_type")
]


class CampaignPayload(BaseModel):
    name: str = Field(default="campaign")
    objective: CampaignObjective = Field(default=CampaignObjective.OUTCOME_LEADS)
    status: Status = Field(default=Status.PAUSED)
    special_ad_categories: list[SpecialAdCategory] | None = Field(default=None)
    special_ad_category_country: list[CountryCode] | None = Field(default=None)

    @model_validator(mode="after")
    def validate_special_ad_category_country(self):
        if (
            self.special_ad_categories
            and SpecialAdCategory.NONE in self.special_ad_categories
        ):
            self.special_ad_categories = [SpecialAdCategory.NONE]
            self.special_ad_category_country = []
        return self


class CreateCampaignRequest(BaseModel):
    ad_account_id: str = Field(..., alias="adAccountId")
    campaign_payload: CampaignPayload = Field(..., alias="campaignPayload")


class LLMAdSetTargeting(BaseModel):
    genders: list[Literal["MALE", "FEMALE"]]
    age_min: int = Field(..., ge=meta_constants.MIN_AGE, le=meta_constants.MAX_AGE)
    age_max: int = Field(..., ge=meta_constants.MIN_AGE, le=meta_constants.MAX_AGE)
    languages: list[str]


class CreateAdSetRequest(BaseModel):
    ad_account_id: str = Field(..., alias="adAccountId", min_length=1)
    campaign_id: str = Field(..., alias="campaignId", min_length=1)
    adset_payload: LLMAdSetTargeting = Field(..., alias="adsetPayload")


class DetailedTargeting(BaseModel):
    interests: list[str] = []
    behaviors: list[str] = []
    demographics: list[str] = []


class CreativeText(BaseModel):
    primary_texts: list[PrimaryTextStr] = Field(
        ..., min_length=1, max_length=meta_constants.MAX_PRIMARY_TEXTS
    )
    headlines: list[HeadlineStr] = Field(
        ..., min_length=1, max_length=meta_constants.MAX_HEADLINES
    )
    descriptions: list[DescriptionStr] = Field(
        ..., min_length=1, max_length=meta_constants.MAX_DESCRIPTIONS
    )
    cta: CallToAction


class CreativeImage(BaseModel):
    image_url: str | None = Field(
        default=None, description="Base64 image (only for preview / upload step)"
    )
    image_hash: str | None = Field(default=None, description="Meta uploaded image hash")

    @model_validator(mode="after")
    def validate_image_source(self):
        if not self.image_url and not self.image_hash:
            raise ValueError("Either image_url or image_hash must be provided")
        return self


class LLMCreativeTextPayload(BaseModel):
    text: CreativeText
    image: CreativeImage | None = None


class CreativeGenerationRequest(BaseModel):
    destination_type: DestinationType


class CreateCreativeRequest(BaseModel):
    adAccountId: str = Field(..., alias="adAccountId")
    creativePayload: LLMCreativeTextPayload = Field(..., alias="creativePayload")


class CreateCreativeResponse(BaseModel):
    creativeId: str = Field(..., alias="creativeId")


class ExistingIdsPayload(BaseModel):
    campaign_id: str | None = None
    adset_id: str | None = None
    creative_id: str | None = None
    ad_id: str | None = None


class AdPayload(BaseModel):
    name: str = Field(..., min_length=1)
    status: Status = Status.PAUSED
    adset_id: str | None = None
    creative: dict[str, Annotated[str, Field(min_length=1)]] | None = (
        None  # creative_id: str
    )


class Schedule(BaseModel):
    start_time: date
    end_time: date | None = None

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def parse_date(cls, value):
        """Parse date string (dd/mm/yyyy or ISO) into a standard date object."""
        if not value:
            return value
        if isinstance(value, str):
            # Try dd/mm/yyyy first (common UI format)
            try:
                return datetime.strptime(value, "%d/%m/%Y").date()
            except Exception:
                # Fallback to ISO format (YYYY-MM-DD)
                try:
                    return datetime.fromisoformat(value).date()
                except Exception:
                    raise ValueError("Date must be in format dd/mm/yyyy or YYYY-MM-DD")

        return value

    @model_validator(mode="after")
    def validate_dates(self):
        """Validate that start_time is not in the past and end_time follows start_time."""
        current_date = datetime.now().date()
        if self.start_time < current_date:
            raise ValueError("start_time cannot be in the past")

        if self.end_time and self.end_time < self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class Locale(BaseModel):
    key: int
    name: str = Field(..., min_length=1)


class Location(BaseModel):
    key: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    radius: int | None = None
    distance_unit: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    @field_validator("distance_unit")
    @classmethod
    def validate_distance_unit(cls, v):
        """Validate that the distance unit is supported by Meta constants."""
        if v and v not in meta_constants.VALID_DISTANCE_UNITS:
            raise ValueError(
                f"Invalid distance_unit: '{v}'. "
                f"Must be one of: {meta_constants.VALID_DISTANCE_UNITS}"
            )
        return v


class TargetingCategory(str, Enum):
    INTERESTS = "interests"
    DEMOGRAPHICS = "demographics"
    BEHAVIORS = "behaviors"


class TargetingEntity(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(..., min_length=1)
    name: str | None = None
    type: str | None = None


class Targeting(BaseModel):
    locations: list[Location]
    locales: list[Locale] | None = None
    behaviors: list[TargetingEntity] | None = None
    interests: list[TargetingEntity] | None = None
    demographics: list[TargetingEntity] | None = None

    age_min: int | None = Field(
        None, ge=meta_constants.MIN_AGE, le=meta_constants.MAX_AGE
    )
    age_max: int | None = Field(
        None, ge=meta_constants.MIN_AGE, le=meta_constants.MAX_AGE
    )
    genders: list[Gender] | None = None

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

        non_demographic_values = {m.value for m in NonDemographicType}

        for i in interests:
            if i.type and i.type.lower() != NonDemographicType.interests.value:
                raise ValueError(f"Invalid type '{i.type}' in interests")

        for b in behaviors:
            if b.type and b.type.lower() != NonDemographicType.behaviors.value:
                raise ValueError(f"Invalid type '{b.type}' in behaviors")

        for d in demographics:
            if d.type and d.type.lower() in non_demographic_values:
                raise ValueError(f"Invalid type '{d.type}' in demographics")

        seen_ids: set[str] = set()
        for group in [interests, behaviors, demographics]:
            for e in group:
                if e.id in seen_ids:
                    raise ValueError(
                        f"Duplicate targeting id '{e.id}' found across groups"
                    )
                seen_ids.add(e.id)

        return values


class Budget(BaseModel):
    amount: int = Field(..., gt=meta_constants.MIN_DAILY_BUDGET_INR)
    type: BudgetType

    def to_meta_payload(self) -> dict:
        """Transform the budget model into a Meta-compatible minor-unit payload."""
        minor_units = int(self.amount * meta_constants.INR_TO_MINOR_UNIT)
        key = "daily_budget" if self.type == BudgetType.DAILY else "lifetime_budget"
        return {key: minor_units}


class Bidding(BaseModel):
    optimization_goal: OptimizationGoal
    billing_event: BillingEvent
    bid_strategy: BidStrategy
    bid_amount: int | None = None

    @model_validator(mode="after")
    def validate_bid_amount(self):
        """Validate that bid_amount is provided if the strategy requires it."""
        if self.bid_strategy.requires_bid_amount and self.bid_amount is None:
            raise ValueError(
                f"bid_amount is required for bid_strategy '{self.bid_strategy.value}'"
            )
        return self


class PromotedObject(BaseModel):
    type: PromotedObjectType
    pixel_id: str | None = Field(default=None, min_length=1)
    event: ConversionEvent | None = None
    application_id: str | None = Field(default=None, min_length=1)
    object_store_url: str | None = Field(default=None, min_length=1)
    page_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_required_fields(self):
        """Ensure all required fields for the specific promoted object type are present."""
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
        """Transform the promoted object into a specific Meta API structure."""
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


class AdSetPayload(BaseModel):
    name: str = Field(..., min_length=1)
    status: Status = Status.PAUSED
    schedule: Schedule | None = None
    targeting: Targeting
    destination_type: DestinationType
    budget: Budget
    bidding: Bidding
    promoted_object: PromotedObject
    campaign_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_lifetime_budget_requires_schedule(self):
        """Ensure a complete schedule is provided if using a LIFETIME budget."""
        if self.budget.type == BudgetType.LIFETIME:
            if self.schedule is None:
                raise ValueError("schedule is required when using a LIFETIME budget")
            if self.schedule.end_time is None:
                raise ValueError(
                    "end_time is required in schedule when using a LIFETIME budget"
                )
        return self


class WebsiteCTA(BaseModel):
    type: CallToAction
    url: str
    lead_gen_form_id: None = None


class LeadGenCTA(BaseModel):
    type: CallToAction
    lead_gen_form_id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)


class BaseCreative(BaseModel):
    name: str = Field(..., min_length=1)
    type: CreativeType
    page_id: str = Field(..., min_length=1)
    instagram_user_id: str | None = Field(default=None, min_length=1)
    destination_type: DestinationType
    image_hashes: list[str] = Field(
        ..., min_length=1, max_length=meta_constants.MAX_IMAGES
    )
    headlines: list[HeadlineStr] = Field(
        ..., min_length=1, max_length=meta_constants.MAX_HEADLINES
    )
    primary_texts: list[PrimaryTextStr] = Field(
        ..., min_length=1, max_length=meta_constants.MAX_PRIMARY_TEXTS
    )
    descriptions: list[DescriptionStr] | None = Field(
        default=None, min_length=1, max_length=meta_constants.MAX_DESCRIPTIONS
    )


class WebsiteCreative(BaseCreative):
    destination_type: Literal[DestinationType.WEBSITE]
    call_to_action: WebsiteCTA
    url_tags: str | None = None

    @field_validator("url_tags", mode="before")
    @classmethod
    def validate_url_tags(cls, value: str | None) -> str | None:
        """Validate and sanitize Meta URL tags and macros."""
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
            key, val = key.strip(), val.strip()

            if key not in valid_keys:
                raise ValueError(
                    f"Unknown url_tag key '{key}'. Allowed keys: {sorted(valid_keys)}"
                )
            if not val:
                raise ValueError(f"url_tag key '{key}' has an empty value")

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


class AssembledMetaPayloads(BaseModel):
    campaign_payload: dict[str, Any]
    adset_payload: dict[str, Any]
    creative_payload: dict[str, Any]
    ad_payload: dict[str, Any]


class MetaAdCreationRequest(BaseModel):
    """Unified request model for creating a full Meta Ad structure."""

    ad_account_id: str = Field(..., min_length=1)
    campaign: CampaignPayload
    adset: AdSetPayload
    creative: CreativePayload
    ad: AdPayload
    existing_ids: ExistingIdsPayload | None = None


class MetaAdCreationResponse(BaseModel):
    """Unified response model containing the final state of all created/recovered IDs."""

    ids: ExistingIdsPayload


# LLM response models
class TargetingSeedsResponse(BaseModel):
    """Parsed LLM response for seed generation."""

    seeds: list[str]


class TargetingFilterResponse(BaseModel):
    """Parsed LLM response for candidate filtering."""

    selected_ids: list[str]


class MetaTargetingSuggestionResult(BaseModel):
    """Complete output returned by the orchestrator."""

    interests: list[TargetingEntity] = []
    demographics: list[TargetingEntity] = []
    behaviors: list[TargetingEntity] = []


class LLMAdSetGenerationResponse(BaseModel):
    """Result model for the adset generation agent."""

    genders: list[Gender]
    age_min: int = Field(..., ge=meta_constants.MIN_AGE, le=meta_constants.MAX_AGE)
    age_max: int = Field(..., ge=meta_constants.MIN_AGE, le=meta_constants.MAX_AGE)
    locales: list[dict]
    flexible_spec: list[dict]
    locations: dict | None = None


class PlacementItem(BaseModel):
    placement: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class PlacementRecommendation(BaseModel):
    inferred_business_type: str = Field(
        ..., description="The industry category the LLM mapped this business to"
    )
    primary: list[PlacementItem]
    secondary: list[PlacementItem]
    avoid: list[PlacementItem]


class MetaPositions(BaseModel):
    effective_facebook_positions: list[str]
    effective_instagram_positions: list[str]

    @model_validator(mode="after")
    def validate_positions(self):
        if (
            not self.effective_facebook_positions
            and not self.effective_instagram_positions
        ):
            raise ValueError("At least one placement position must be provided.")
        return self

    @computed_field
    @property
    def effective_publisher_platforms(self) -> list[str]:
        platforms = []
        if self.effective_facebook_positions:
            platforms.append("facebook")
        if self.effective_instagram_positions:
            platforms.append("instagram")
        return platforms


class MetaAdsPlacementResponse(BaseModel):
    meta_positions: MetaPositions
    recommendation: PlacementRecommendation


class PlacementRequest(BaseModel):
    objective: CampaignObjective
    creative_type: CreativeType


META_CTA_MAPPING: dict[CampaignObjective, dict[DestinationType, list[CallToAction]]] = {
    CampaignObjective.OUTCOME_LEADS: {
        DestinationType.ON_AD: [
            CallToAction.APPLY_NOW,
            CallToAction.BOOK_NOW,
            CallToAction.DOWNLOAD,
            CallToAction.GET_OFFER,
            CallToAction.GET_QUOTE,
            CallToAction.LEARN_MORE,
            CallToAction.SIGN_UP,
            CallToAction.SUBSCRIBE,
        ],
        DestinationType.WEBSITE: [
            CallToAction.CONTACT_US,
            CallToAction.SIGN_UP,
            CallToAction.GET_QUOTE,
            CallToAction.BOOK_NOW,
            CallToAction.APPLY_NOW,
            CallToAction.LEARN_MORE,
            CallToAction.SUBSCRIBE,
        ],
    }
}
