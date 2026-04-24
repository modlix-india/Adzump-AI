import structlog
from agents.shared.llm import chat_completion
from utils.prompt_loader import load_prompt
from exceptions.custom_exceptions import (
    AIProcessingException,
    BusinessValidationException,
    SessionException,
)
from services.session_manager import sessions
from core.models.meta import (
    PlacementRecommendation,
    CampaignObjective,
    CreativeType,
)
from services.business_service import BusinessService
from types import MappingProxyType
from core.models.meta import MetaAdsPlacementResponse
from pydantic import ValidationError
from core.models.meta import MetaPositions

logger = structlog.get_logger(__name__)
LLM_MODEL = "gpt-4o-mini"

# MAPPING (BUSINESS → META API)


_PLACEMENT_MAPPING = {
    "facebook_feed": {"platform": "facebook", "position": "feed"},
    "facebook_profile_feed": {"platform": "facebook", "position": "profile_feed"},
    "facebook_marketplace": {"platform": "facebook", "position": "marketplace"},
    "facebook_stories": {"platform": "facebook", "position": "story"},
    "facebook_reels": {"platform": "facebook", "position": "facebook_reels"},
    "facebook_instream_reels": {
        "platform": "facebook",
        "position": "facebook_reels_overlay",
    },
    "instagram_feed": {"platform": "instagram", "position": "stream"},
    "instagram_profile_feed": {"platform": "instagram", "position": "profile_feed"},
    "instagram_explore": {"platform": "instagram", "position": "explore"},
    "instagram_explore_home": {"platform": "instagram", "position": "explore_home"},
    "instagram_stories": {"platform": "instagram", "position": "story"},
    "instagram_reels": {"platform": "instagram", "position": "reels"},
}

PLACEMENT_MAPPING = MappingProxyType(_PLACEMENT_MAPPING)
VALID_PLACEMENTS = set(PLACEMENT_MAPPING.keys())

# AGENT


class MetaAdsPlacementAgent:
    def __init__(self):
        self._business_service: BusinessService | None = None

    @property
    def business_service(self) -> BusinessService:
        if self._business_service is None:
            self._business_service = BusinessService()
        return self._business_service

    async def generate_placements(
        self,
        session_id: str,
        objective: str,
        creative_type: str,
    ) -> MetaAdsPlacementResponse:

        if session_id not in sessions:
            logger.warning("ads_placement.invalid_session", session_id=session_id)
            raise SessionException("Session not found")

        # FETCH WEBSITE DATA
        website_data = await self.business_service.fetch_website_data(session_id)

        summary = website_data.final_summary or website_data.summary
        if not summary:
            raise BusinessValidationException(
                "Missing summary in product data. Please complete website analysis."
            )

        # VALIDATION
        try:
            # Ensure objective is valid
            if objective not in [o.value for o in CampaignObjective]:
                valid_objectives = [o.value for o in CampaignObjective]
                raise BusinessValidationException(
                    f"Invalid objective: '{objective}'. Allowed values: {valid_objectives}"
                )

            # Ensure creative_type is valid
            if creative_type not in [c.value for c in CreativeType]:
                valid_creatives = [c.value for c in CreativeType]
                raise BusinessValidationException(
                    f"Invalid creative_type: '{creative_type}'. Allowed values: {valid_creatives}"
                )
        except Exception as e:
            if isinstance(e, BusinessValidationException):
                raise e
            logger.error("ads_placement.validation_error", error=str(e))
            raise BusinessValidationException(f"Validation failed: {str(e)}")

        logger.info(
            "ads_placement.post_validation_started",
            objective=objective,
            creative_type=creative_type,
            summary=summary,
        )

        # STEP 1: LLM CALL
        placements = await self._generate_placements_from_llm(
            objective=objective,
            creative_type=creative_type,
            summary=summary,
        )

        logger.info(
            "ads_placement.after_llm",
            primary=[p.placement for p in placements.primary],
            secondary=[p.placement for p in placements.secondary],
            avoid=[p.placement for p in placements.avoid],
        )

        # STEP 2: TRANSFORM → META STRUCTURE
        meta_payload = self._map_to_meta_positions(placements)

        # STEP 3: FINAL RESPONSE
        return MetaAdsPlacementResponse(
            meta_positions=meta_payload, recommendation=placements
        )

    # LLM CALL
    async def _generate_placements_from_llm(
        self,
        objective: str,
        creative_type: str,
        summary: str,
    ) -> PlacementRecommendation:

        template = load_prompt("meta/ads_placement.txt")

        prompt = template.format(
            objective=objective,
            creative_type=creative_type,
            summary=summary,
            allowed_placements="\n".join(sorted(VALID_PLACEMENTS)),
        )

        messages = [
            {
                "role": "system",
                "content": ("You are an expert Meta Ads Placement analyst."),
            },
            {"role": "user", "content": prompt},
        ]

        response = await chat_completion(
            messages, model=LLM_MODEL, response_format={"type": "json_object"}
        )

        if (
            not response
            or not response.choices
            or len(response.choices) == 0
            or not response.choices[0].message
        ):
            raise AIProcessingException("Invalid LLM response structure")

        raw_output = response.choices[0].message.content

        if not raw_output:
            raise AIProcessingException("Ads placement LLM returned empty response")

        try:
            # Pydantic validation
            validated = PlacementRecommendation.model_validate_json(raw_output)

            # SINGLE SUCCESS LOG (after validation only)
            logger.info(
                "ads_placement.llm_validated_success",
                primary=[p.placement for p in validated.primary],
                secondary=[p.placement for p in validated.secondary],
                avoid=[p.placement for p in validated.avoid],
            )

            return validated
        except ValidationError as ve:
            logger.error(
                "ads_placement.schema_validation_failed",
                error=str(ve),
                raw=raw_output,
            )
            raise AIProcessingException(
                "LLM returned invalid schema for placement response"
            )

        except Exception as e:
            logger.error(
                "ads_placement.unexpected_parse_error",
                error=str(e),
                raw=raw_output,
            )
            raise AIProcessingException("Unexpected error while parsing LLM response")

    # TRANSFORMATION LAYER

    def _map_to_meta_positions(
        self, placements: PlacementRecommendation
    ) -> MetaPositions:

        # EXTRACT placement strings
        selected = (
            {p.placement for p in placements.primary if p.placement in VALID_PLACEMENTS}
            | {
                p.placement
                for p in placements.secondary
                if p.placement in VALID_PLACEMENTS
            }
        ) - {p.placement for p in placements.avoid if p.placement in VALID_PLACEMENTS}

        selected_placements = list(selected)

        effective_facebook_positions = set()
        effective_instagram_positions = set()

        for placement in selected_placements:
            mapping = PLACEMENT_MAPPING.get(placement)

            if not mapping:
                continue

            platform = mapping["platform"]
            position = mapping["position"]

            if platform == "facebook":
                effective_facebook_positions.add(position)
            elif platform == "instagram":
                effective_instagram_positions.add(position)

        # FALLBACK
        if not effective_facebook_positions and not effective_instagram_positions:
            logger.warning(
                "ads_placement.fallback_triggered",
                reason="all placements filtered out after validation",
                fallback="facebook_feed:feed",
            )
            effective_facebook_positions.add("feed")

        return MetaPositions(
            effective_facebook_positions=list(effective_facebook_positions),
            effective_instagram_positions=list(effective_instagram_positions),
        )


# INSTANCE
meta_ads_placement_agent = MetaAdsPlacementAgent()
