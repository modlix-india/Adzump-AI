import structlog
from typing import Optional
from adapters.google.mutation.mutation_config import CONFIG
from exceptions.custom_exceptions import BusinessValidationException
from core.models.optimization import (
    ProximityRecommendation,
    SitelinkRecommendation,
    AgeFieldRecommendation,
    GenderFieldRecommendation,
    KeywordRecommendation,
)

logger = structlog.get_logger(__name__)


class MutationValidator:
    """Centralized validator for Google Ads mutation business rules."""

    # AGE VALIDATION
    @staticmethod
    def validate_age_range(age: AgeFieldRecommendation) -> Optional[str]:
        """Validate age range type against official Google Ads API enum values."""
        if not age.age_range or not age.age_range.strip():
            return "Age range is required"

        if age.age_range.upper() not in CONFIG.AGE.VALID_RANGES:
            return (
                f"Invalid age range: '{age.age_range}'. "
                f"Must be one of: {', '.join(sorted(CONFIG.AGE.VALID_RANGES))}"
            )

        return None

    # GENDER VALIDATION
    @staticmethod
    def validate_gender_type(gender: GenderFieldRecommendation) -> Optional[str]:
        """Validate gender type against official Google Ads API enum values."""
        if not gender.gender_type or not gender.gender_type.strip():
            return "Gender type is required"

        if gender.gender_type.upper() not in CONFIG.GENDER.VALID_TYPES:
            return (
                f"Invalid gender type: '{gender.gender_type}'. "
                f"Must be one of: {', '.join(sorted(CONFIG.GENDER.VALID_TYPES))}"
            )

        return None

    @staticmethod
    def validate_radius(proximity: ProximityRecommendation) -> bool:
        """Validate proximity radius constraints (1 km to 800 km / 500 miles)."""
        # Validate units
        if (
            not proximity.radius_units
            or proximity.radius_units.upper() not in CONFIG.PROXIMITY.VALID_UNITS
        ):
            logger.error(
                "Invalid proximity radius units",
                units=proximity.radius_units,
                valid_units=list(CONFIG.PROXIMITY.VALID_UNITS),
            )
            return False

        radius_km = (
            proximity.radius * CONFIG.PROXIMITY.MILES_TO_KM
            if proximity.radius_units == "MILES"
            else proximity.radius
        )
        if (
            radius_km < CONFIG.PROXIMITY.MIN_RADIUS_KM
            or radius_km > CONFIG.PROXIMITY.MAX_RADIUS_KM
        ):
            logger.error(
                "Proximity radius out of bounds",
                radius=proximity.radius,
                units=proximity.radius_units,
                limit_min=CONFIG.PROXIMITY.MIN_RADIUS_KM,
                limit_max=CONFIG.PROXIMITY.MAX_RADIUS_KM,
            )
            return False
        return True

    # TEXT VALIDATION
    @staticmethod
    def validate_text_length(text: str, max_length: int, field_name: str) -> bool:
        """Validate text length constraints."""
        if len(text) > max_length:
            logger.error(
                f"{field_name} too long",
                text=text,
                length=len(text),
                limit=max_length,
            )
            return False
        return True

    # URL VALIDATION
    @staticmethod
    def validate_url(url: str, field_name: str = "URL") -> bool:
        """Validate URL length (limit: 2048 chars)."""
        if not url:
            return True
        if len(url) > CONFIG.URL_MAX_LENGTH:
            logger.error(
                f"{field_name} too long",
                url=url,
                length=len(url),
                limit=CONFIG.URL_MAX_LENGTH,
            )
            return False
        return True

    # SITELINK VALIDATION
    @staticmethod
    def validate_sitelink(sl: SitelinkRecommendation) -> Optional[str]:
        """Comprehensive validation for sitelink recommendations."""
        if not sl.link_text or not sl.link_text.strip():
            return "Link text required"
        if len(sl.link_text) > CONFIG.SITELINKS.LINK_TEXT_MAX_LENGTH:
            return f"Link text too long ({len(sl.link_text)} > {CONFIG.SITELINKS.LINK_TEXT_MAX_LENGTH})"

        if (
            sl.description1
            and len(sl.description1) > CONFIG.SITELINKS.DESCRIPTION_MAX_LENGTH
        ):
            return f"Description 1 too long ({len(sl.description1)} > {CONFIG.SITELINKS.DESCRIPTION_MAX_LENGTH})"

        if (
            sl.description2
            and len(sl.description2) > CONFIG.SITELINKS.DESCRIPTION_MAX_LENGTH
        ):
            return f"Description 2 too long ({len(sl.description2)} > {CONFIG.SITELINKS.DESCRIPTION_MAX_LENGTH})"

        if not sl.final_url:
            return "Final URL required"

        if not MutationValidator.validate_url(sl.final_url, "Final URL"):
            return "Final URL too long"

        if sl.final_mobile_url and not MutationValidator.validate_url(
            sl.final_mobile_url, "Final Mobile URL"
        ):
            return "Final Mobile URL too long"

        if sl.recommendation == "UPDATE" and not sl.asset_resource_name:
            return "UPDATE requires asset_resource_name"

        if sl.recommendation == "REMOVE" and not sl.campaign_asset_resource_name:
            return "REMOVE requires campaign_asset_resource_name"

        return None

    # KEYWORD VALIDATION
    @staticmethod
    def validate_keyword(keyword: KeywordRecommendation) -> Optional[str]:
        """Validate keyword text and match type."""
        # Check text length
        limit = CONFIG.KEYWORDS.MAX_LENGTH
        if len(keyword.text) > limit:
            return f"Keyword text too long ({len(keyword.text)} > {limit})"

        # Check match type
        match_type = keyword.match_type
        if not match_type or not match_type.strip():
            return "Keyword match type is required"

        if match_type.upper() not in CONFIG.KEYWORDS.VALID_MATCH_TYPES:
            return (
                f"Invalid match type: '{match_type}'. "
                f"Must be one of: {', '.join(sorted(CONFIG.KEYWORDS.VALID_MATCH_TYPES))}"
            )
        return None

    # CONTEXT VALIDATION
    @staticmethod
    def validate_context(context, campaign_id: str) -> bool:
        """Validate that the mutation context has required account IDs."""
        if not context.account_id or not context.parent_account_id:
            raise BusinessValidationException(
                "Missing required account IDs",
                details={
                    "customer_id": context.account_id,
                    "login_customer_id": context.parent_account_id,
                    "campaign_id": campaign_id,
                },
            )
        return True
