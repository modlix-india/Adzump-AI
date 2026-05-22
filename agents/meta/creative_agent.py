import json
import base64

import structlog
from pydantic import ValidationError

from adapters.meta.creatives import MetaCreativeAdapter
from core.models.meta import (
    LLMCreativeTextPayload,
    LLMCarouselPayload,
    CreateCreativeRequest,
    CreateCreativeResponse,
    CallToAction,
    CreativeImage,
    DestinationType,
    META_CTA_MAPPING,
    CampaignObjective,
)
from exceptions.custom_exceptions import (
    AIProcessingException,
    BusinessValidationException,
)
from services.business_service import BusinessService
from services.session_manager import sessions, get_website_url
from adapters.gemini.client import generate_images
from agents.shared.llm import chat_completion
from utils.prompt_loader import load_prompt
from adapters.meta.images import MetaAdImageAdapter

logger = structlog.get_logger()

STRATEGY_PROMPT = load_prompt("meta/creative_strategy.txt")
TEXT_PROMPT = load_prompt("meta/creative_text.txt")
IMAGE_INTENT_PROMPT = load_prompt("meta/image_scene.txt")
CAROUSEL_TEXT_PROMPT = load_prompt("meta/carousel_text.txt")

ALLOWED_CTAS = {c.value for c in CallToAction}


def _extract_json(text: str) -> str:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return text[start : end + 1]
    return text


def normalize_cta(value: str) -> str:
    if not value:
        return CallToAction.LEARN_MORE.value

    value = value.upper().strip()
    return value if value in ALLOWED_CTAS else CallToAction.LEARN_MORE.value


def get_valid_ctas(
    objective: CampaignObjective, destination_type: DestinationType
) -> str:
    valid_ctas = META_CTA_MAPPING.get(objective, {}).get(
        destination_type, [CallToAction.LEARN_MORE]
    )
    return ", ".join(cta.value for cta in valid_ctas)


class MetaCreativeAgent:
    def __init__(self):
        self.business_service = BusinessService()
        self.creative_adapter = MetaCreativeAdapter()

    async def generate_payload(
        self,
        session_id: str,
        destination_type: DestinationType,
    ) -> LLMCreativeTextPayload:

        if session_id not in sessions:
            raise BusinessValidationException("Session not found")

        summary = sessions[session_id].get("campaign_data", {}).get("business_summary")

        if not summary:
            raise BusinessValidationException("Missing business summary in session.")

        strategy_raw = await chat_completion(
            [{"role": "user", "content": STRATEGY_PROMPT.format(summary=summary)}]
        )
        strategy_json = _extract_json(strategy_raw.choices[0].message.content)

        # Cache summary and strategy for image generation
        sessions[session_id].setdefault("campaign_data", {})
        sessions[session_id]["campaign_data"]["business_summary"] = summary
        sessions[session_id]["campaign_data"]["visual_strategy"] = strategy_json

        valid_ctas = get_valid_ctas(CampaignObjective.OUTCOME_LEADS, destination_type)

        text_raw = await chat_completion(
            [
                {
                    "role": "user",
                    "content": TEXT_PROMPT.format(
                        summary=summary,
                        strategy=strategy_json,
                        valid_ctas=valid_ctas,
                    ),
                }
            ]
        )
        text_json = json.loads(_extract_json(text_raw.choices[0].message.content))
        text_json["cta"] = normalize_cta(text_json.get("cta"))

        try:
            creative_payload = LLMCreativeTextPayload(text=text_json)
        except ValidationError as e:
            logger.error(
                "Creative payload validation failed",
                error=str(e),
                raw_text=text_json,
            )
            raise AIProcessingException("Invalid creative payload from LLM")

        return creative_payload

    async def generate_carousel_payload(
        self,
        session_id: str,
        card_count: int = 5,
    ) -> LLMCarouselPayload:

        if session_id not in sessions:
            raise BusinessValidationException("Session not found")

        summary = sessions[session_id].get("campaign_data", {}).get("business_summary")
        if not summary:
            raise BusinessValidationException("Missing business summary in session.")

        sessions[session_id].setdefault("campaign_data", {})
        sessions[session_id]["campaign_data"]["business_summary"] = summary

        valid_ctas = get_valid_ctas(CampaignObjective.OUTCOME_LEADS, DestinationType.WEBSITE)

        text_raw = await chat_completion(
            [{"role": "user", "content": CAROUSEL_TEXT_PROMPT.format(
                summary=summary,
                card_count=card_count,
                valid_ctas=valid_ctas,
            )}]
        )
        text_json = json.loads(_extract_json(text_raw.choices[0].message.content))
        text_json["cta"] = normalize_cta(text_json.get("cta"))

        website_url = get_website_url(session_id)
        text_json.pop("cta_url", None)

        try:
            payload = LLMCarouselPayload(**text_json, cta_url=website_url)
        except ValidationError as e:
            logger.error("Carousel payload validation failed", error=str(e), raw=text_json)
            raise AIProcessingException("Invalid carousel payload from LLM")

        return payload

    async def generate_image(
        self,
        session_id: str,
        ad_account_id: str,
    ) -> CreativeImage:

        if session_id not in sessions:
            raise BusinessValidationException("Session not found")

        campaign_data = sessions[session_id].get("campaign_data", {})

        summary = campaign_data.get("business_summary")
        strategy_json = campaign_data.get("visual_strategy")

        if not summary or not strategy_json:
            raise BusinessValidationException(
                "Creative text must be generated before image"
            )

        if not ad_account_id:
            raise BusinessValidationException(
                "adAccountId is required to generate image"
            )

        logger.info(
            "Generating image generation intent",
            summary=summary,
            visual_directive=strategy_json,
        )
        image_intent_raw = await chat_completion(
            [
                {
                    "role": "user",
                    "content": IMAGE_INTENT_PROMPT.format(
                        summary=summary,
                        visual_directive=strategy_json,
                    ),
                }
            ]
        )
        image_intent_json = _extract_json(image_intent_raw.choices[0].message.content)

        try:
            images = await generate_images(image_intent_json, n=1)
            if not images:
                raise AIProcessingException("Image generation returned empty results")

            image_base64 = base64.b64encode(images[0]).decode("utf-8")
            image_adapter = MetaAdImageAdapter()

            upload_result = await image_adapter.upload_image(
                ad_account_id=ad_account_id,
                image_base64=image_base64,
            )

            image_data = next(iter(upload_result["images"].values()))
            image_hash = image_data["hash"]

            logger.info("Meta creative image saved", image_hash=image_hash)
            return CreativeImage(image_hash=image_hash)

        except AIProcessingException:
            raise

        except Exception as e:
            logger.error(
                "Image generation or upload failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise AIProcessingException(f"Image generation failed: {str(e)}") from e

    async def create_creative(
        self, request: CreateCreativeRequest
    ) -> CreateCreativeResponse:

        session = sessions.get(request.session_id)
        if not session:
            raise BusinessValidationException("Session not found")

        ad_plan = session.get("ad_plan") or {}

        page_id = ad_plan.get("metaPageId") or session.get("metaPageId")

        # TEMP: Hardcoded Meta page ID for development
        if not page_id:
            page_id = "332515906622723"

        if not request.creativePayload.image:
            raise BusinessValidationException("Image required before creating creative")

        if not request.creativePayload.image.image_hash:
            raise BusinessValidationException(
                "image_hash is required to create Meta creative"
            )

        result = await self.creative_adapter.create(
            ad_account_id=request.adAccountId,
            creative_payload=request.creativePayload.model_dump(mode="json"),
            page_id=page_id,
        )

        return CreateCreativeResponse(creativeId=result["id"])


meta_creative_agent = MetaCreativeAgent()
