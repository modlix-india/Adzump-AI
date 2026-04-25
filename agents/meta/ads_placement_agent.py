import json
from functools import cached_property
from types import MappingProxyType

import structlog
from pydantic import ValidationError

from agents.shared.llm import chat_completion
from core.models.meta import (
    CampaignObjective,
    CreativeType,
    MetaAdsPlacementResponse,
    MetaPositions,
    PlacementRecommendation,
)
from exceptions.custom_exceptions import (
    AIProcessingException,
    BusinessValidationException,
    SessionException,
)
from services.business_service import BusinessService
from services.session_manager import sessions
from utils.prompt_loader import load_prompt

logger = structlog.get_logger(__name__)

OPENAI_MODEL = "gpt-4o-mini"

# Map human-readable placement names to Meta API platform/position codes.
# Keys are used in prompts and LLM output; values are sent to the Meta Ads API.
_PLACEMENT_MAPPING = {
    # Facebook placements
    "facebook_feed": {"platform": "facebook", "position": "feed"},
    "facebook_profile_feed": {"platform": "facebook", "position": "profile_feed"},
    "facebook_marketplace": {"platform": "facebook", "position": "marketplace"},
    "facebook_stories": {"platform": "facebook", "position": "story"},
    "facebook_reels": {"platform": "facebook", "position": "facebook_reels"},
    "facebook_instream_reels": {
        "platform": "facebook",
        "position": "facebook_reels_overlay",
    },
    # Instagram placements
    "instagram_feed": {"platform": "instagram", "position": "stream"},
    "instagram_profile_feed": {"platform": "instagram", "position": "profile_feed"},
    "instagram_explore": {"platform": "instagram", "position": "explore"},
    "instagram_explore_home": {"platform": "instagram", "position": "explore_home"},
    "instagram_stories": {"platform": "instagram", "position": "story"},
    "instagram_reels": {"platform": "instagram", "position": "reels"},
}

# Immutable view to prevent accidental mutation at runtime
PLACEMENT_MAPPING = MappingProxyType(_PLACEMENT_MAPPING)

# Frozen set of valid placement keys used for LLM output validation
VALID_PLACEMENTS = frozenset(PLACEMENT_MAPPING.keys())


class MetaAdsPlacementAgent:
    """Generate Meta Ads placement recommendations using LLM analysis.

    Uses business context (website summary), campaign objective, and
    creative type to recommend optimal Facebook/Instagram ad placements
    based on industry-specific rules.
    """

    @cached_property
    def business_service(self) -> BusinessService:
        """Return lazily-initialized BusinessService instance."""
        return BusinessService()

    async def generate_placements(
        self,
        session_id: str,
        objective: CampaignObjective,
        creative_type: CreativeType,
    ) -> MetaAdsPlacementResponse:
        """Generate placement recommendations and map them to Meta API positions."""

        # Automatically includes session_id, objective, creative_type
        structlog.contextvars.bind_contextvars(
            session_id=session_id,
            objective=objective.value,
            creative_type=creative_type.value,
        )

        try:
            logger.info("ads_placement.request_received")

            # Enforce initial version scope restrictions.
            if objective != CampaignObjective.OUTCOME_LEADS:
                raise BusinessValidationException(
                    f"Objective {objective.value} is not currently supported. "
                    "Only OUTCOME_LEADS is supported."
                )
            if creative_type != CreativeType.IMAGE:
                raise BusinessValidationException(
                    f"Creative type {creative_type.value} is not currently supported. "
                    "Only IMAGE is supported."
                )

            # Verify session validity before proceeding.
            if session_id not in sessions:
                raise SessionException("Session not found")

            # Retrieve the business context required for placement generation.
            website_data = await self.business_service.fetch_website_data(session_id)

            # Ensure website analysis is complete and summary is available.
            summary = website_data.final_summary or website_data.summary
            if not summary:
                raise BusinessValidationException(
                    "Missing summary in product data. Please complete website analysis."
                )

            # Generate placements using LLM and industry rules.
            placements = await self._generate_placements_from_llm(
                objective=objective,
                creative_type=creative_type,
                summary=summary,
            )

            # Map human-readable placements to Meta API position codes.
            meta_positions = self._map_to_meta_positions(placements)

            logger.info(
                "ads_placement.generate_completed",
                facebook_positions=meta_positions.effective_facebook_positions,
                instagram_positions=meta_positions.effective_instagram_positions,
                publisher_platforms=meta_positions.effective_publisher_platforms,
                inferred_business_type=placements.inferred_business_type,
            )

            return MetaAdsPlacementResponse(
                meta_positions=meta_positions, recommendation=placements
            )

        finally:
            # Always clear context vars after the request — even on exception.
            # Prevents session_id, objective, creative_type from leaking
            # into the next request handled by this worker.
            structlog.contextvars.clear_contextvars()

    async def _generate_placements_from_llm(
        self,
        objective: CampaignObjective,
        creative_type: CreativeType,
        summary: str,
    ) -> PlacementRecommendation:
        """Call LLM with industry rules and validate the response against PlacementRecommendation schema."""
        template = load_prompt("meta/ads_placement.txt")

        prompt = template.format(
            objective=objective.value,
            creative_type=creative_type.value,
            summary=summary,
            allowed_placements="\n".join(sorted(VALID_PLACEMENTS)),
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a Meta Ads placement strategist. "
                    "First infer the business type from the summary, "
                    "then recommend placements using only the allowed placement names — "
                    "every allowed placement must appear in exactly one tier."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        response = await chat_completion(
            messages, model=OPENAI_MODEL, response_format={"type": "json_object"}
        )

        if not response or not response.choices:
            raise AIProcessingException("Invalid LLM response structure")

        raw_output = response.choices[0].message.content

        if not raw_output:
            raise AIProcessingException("Ads placement LLM returned empty response")

        try:
            validated = PlacementRecommendation.model_validate_json(raw_output)
        except (json.JSONDecodeError, ValidationError) as exc:
            raw_preview = (
                raw_output[:300] + "..." if len(raw_output) > 300 else raw_output
            )
            raise AIProcessingException(
                "Failed to parse LLM placement response",
                details={
                    "error_type": type(exc).__name__,
                    "raw_output_preview": raw_preview,
                    "raw_output_length": len(raw_output),
                },
            ) from exc

        logger.info(
            "ads_placement.llm_generation_success",
            inferred_business_type=validated.inferred_business_type,
            primary=[item.placement for item in validated.primary],
            secondary=[item.placement for item in validated.secondary],
            avoid=[item.placement for item in validated.avoid],
        )

        return validated

    def _map_to_meta_positions(
        self,
        placements: PlacementRecommendation,
    ) -> MetaPositions:
        """Merge primary/secondary placements, remove avoided ones, and map to Meta API position codes."""

        # Collect valid placements from each priority tier
        primary_names = {
            item.placement
            for item in placements.primary
            if item.placement in VALID_PLACEMENTS
        }
        secondary_names = {
            item.placement
            for item in placements.secondary
            if item.placement in VALID_PLACEMENTS
        }
        avoided_names = {
            item.placement
            for item in placements.avoid
            if item.placement in VALID_PLACEMENTS
        }

        # Merge candidates and exclude avoided
        selected = (primary_names | secondary_names) - avoided_names

        facebook_positions: set[str] = set()
        instagram_positions: set[str] = set()

        for placement in selected:
            mapping = PLACEMENT_MAPPING.get(placement)
            if not mapping:
                continue

            if mapping["platform"] == "facebook":
                facebook_positions.add(mapping["position"])
            elif mapping["platform"] == "instagram":
                instagram_positions.add(mapping["position"])

        if not facebook_positions and not instagram_positions:
            # session_id automatically included via contextvars
            logger.warning(
                "ads_placement.fallback_triggered",
                reason="all placements filtered out after validation",
                fallback="facebook_feed:feed",
            )
            facebook_positions.add("feed")

        return MetaPositions(
            effective_facebook_positions=list(facebook_positions),
            effective_instagram_positions=list(instagram_positions),
        )


meta_ads_placement_agent = MetaAdsPlacementAgent()
