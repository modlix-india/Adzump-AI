import structlog
from typing import Optional
from adapters.google.mutation.mutation_config import CONFIG
from core.models.optimization import (
    ProximityRecommendation,
    SitelinkRecommendation,
    KeywordRecommendation,
)

logger = structlog.get_logger(__name__)


class MutationValidator:
    """Centralized validator for Google Ads mutation business rules."""

    @staticmethod
    def validate_radius(proximity: ProximityRecommendation) -> bool:
        """Validate proximity radius constraints (1 km to 800 km / 500 miles)."""
        # Units are validated by Literal["MILES", "KILOMETERS"] in the model

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
        # link_text and final_url presence are enforced by the model (min_length=1)
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
        """Validate keyword text length (match_type is validated by Literal in model)."""
        limit = CONFIG.KEYWORDS.MAX_LENGTH
        if len(keyword.text) > limit:
            return f"Keyword text too long ({len(keyword.text)} > {limit})"
        return None
