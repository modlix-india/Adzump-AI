import structlog
import json
import re

from agents.shared.llm import chat_completion
from utils.prompt_loader import load_prompt
from exceptions.custom_exceptions import (
    AIProcessingException,
    BusinessValidationException,
)

from pydantic import BaseModel

from services.business_service import BusinessService

logger = structlog.get_logger()

# RESPONSE MODELS


class PlacementItem(BaseModel):
    placement: str
    reason: str


class PlacementRecommendation(BaseModel):
    primary: list[PlacementItem]
    secondary: list[PlacementItem]
    avoid: list[PlacementItem]


# MAPPING (BUSINESS → META API)
PLACEMENT_MAPPING = {
    "facebook_feed": {"platform": "facebook", "position": "feed"},
    "facebook_profile_feed": {"platform": "facebook", "position": "profile_feed"},
    "facebook_marketplace": {"platform": "facebook", "position": "marketplace"},
    "facebook_stories": {"platform": "facebook", "position": "story"},
    "facebook_reels": {"platform": "facebook", "position": "facebook_reels"},
    "facebook_instream_reels": {"platform": "facebook", "position": "instream_video"},
    "instagram_feed": {"platform": "instagram", "position": "stream"},
    "instagram_profile_feed": {"platform": "instagram", "position": "profile_feed"},
    "instagram_explore": {"platform": "instagram", "position": "explore"},
    "instagram_explore_home": {"platform": "instagram", "position": "explore_home"},
    "instagram_stories": {"platform": "instagram", "position": "story"},
    "instagram_reels": {"platform": "instagram", "position": "reels"},
}


# AGENT


class MetaAdsPlacementAgent:
    def __init__(self):
        self.business_service = BusinessService()
        logger.info("ads_placement.agent_initialized")

    async def generate_placements(
        self,
        session_id: str,
        ad_account_id: str,
        objective: str,
        creative_type: str,
    ) -> dict:

        # FETCH WEBSITE DATA
        website_data = await self.business_service.fetch_website_data(session_id)

        summary = website_data.final_summary or website_data.summary
        if not summary:
            raise BusinessValidationException(
                "Missing summary in product data. Please complete website analysis."
            )

        business_type = website_data.business_type or ""
        industry = business_type.strip()

        logger.info(
            "ads_placement.generate_started",
            objective=objective,
            creative_type=creative_type,
            industry=industry,
            ad_account_id=ad_account_id,
        )

        # STEP 1: LLM CALL
        placements = await self._generate_placements_from_llm(
            objective=objective,
            creative_type=creative_type,
            industry=industry,
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
        return {
            "meta_positions": meta_payload,
            "recommendation": self._build_recommendation_output(placements),
        }

    # LLM CALL
    async def _generate_placements_from_llm(
        self,
        objective: str,
        creative_type: str,
        industry: str,
    ) -> PlacementRecommendation:

        template = load_prompt("meta/ads_placement.txt")

        prompt = template.format(
            objective=objective,
            creative_type=creative_type,
            industry=industry,
        )

        messages = [
            {
                "role": "system",
                "content": "Return ONLY valid JSON.",
            },
            {"role": "user", "content": prompt},
        ]

        response = await chat_completion(messages, model="gpt-4.1-mini")

        raw_output = response.choices[0].message.content

        logger.info("ads_placement.llm_raw_output", raw_output=raw_output)

        if not raw_output:
            raise AIProcessingException("Ads placement LLM returned empty response")

        try:
            # CLEAN OUTPUT (important)
            cleaned = raw_output.strip()
            cleaned = re.sub(r"^```json", "", cleaned)
            cleaned = re.sub(r"```$", "", cleaned).strip()

            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                cleaned = match.group(0)

            parsed_dict = json.loads(cleaned)

            return PlacementRecommendation.model_validate(parsed_dict)

        except Exception as e:
            logger.error(
                "ads_placement.parse_failed",
                error=str(e),
                raw=raw_output,
            )
            raise AIProcessingException("Ads placement output is not valid JSON")

    # BUILD RECOMMENDATION OUTPUT
    def _build_recommendation_output(self, placements: PlacementRecommendation):
        return {
            "primary": [item.model_dump() for item in placements.primary],
            "secondary": [item.model_dump() for item in placements.secondary],
            "avoid": [item.model_dump() for item in placements.avoid],
        }

    # TRANSFORMATION LAYER

    def _map_to_meta_positions(self, placements: PlacementRecommendation) -> dict:

        VALID_PLACEMENTS = set(PLACEMENT_MAPPING.keys())

        # EXTRACT placement strings
        primary = [
            p.placement for p in placements.primary if p.placement in VALID_PLACEMENTS
        ]
        secondary = [
            p.placement for p in placements.secondary if p.placement in VALID_PLACEMENTS
        ]
        avoid = {p.placement for p in placements.avoid}

        # REMOVE avoid conflicts
        primary = [p for p in primary if p not in avoid]
        secondary = [p for p in secondary if p not in avoid]

        # MERGE priority
        selected_placements = []
        selected_placements.extend(primary)

        for p in secondary:
            if p not in selected_placements:
                selected_placements.append(p)

        facebook_positions = set()
        instagram_positions = set()

        for placement in selected_placements:
            mapping = PLACEMENT_MAPPING.get(placement)

            if not mapping:
                continue

            if mapping["platform"] == "facebook":
                facebook_positions.add(mapping["position"])

            elif mapping["platform"] == "instagram":
                instagram_positions.add(mapping["position"])

        # FALLBACK
        if not facebook_positions and not instagram_positions:
            facebook_positions.add("feed")

        return {
            "facebook_positions": list(facebook_positions),
            "instagram_positions": list(instagram_positions),
            "publisher_platforms": self._get_publisher_platforms(
                facebook_positions,
                instagram_positions,
            ),
        }

    # PLATFORM BUILDER
    def _get_publisher_platforms(
        self, fb_positions: set, ig_positions: set
    ) -> list[str]:
        platforms = []

        if fb_positions:
            platforms.append("facebook")

        if ig_positions:
            platforms.append("instagram")

        return platforms


# INSTANCE
meta_ads_placement_agent = MetaAdsPlacementAgent()
