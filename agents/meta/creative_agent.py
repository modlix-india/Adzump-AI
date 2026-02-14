# from datetime import datetime
from typing import Any
import json
import os
import base64

import structlog
from pydantic import ValidationError

from adapters.meta.creatives import MetaCreativeAdapter
from adapters.meta.models import (
    CreativePayload,
    CreateCreativeRequest,
    CreateCreativeResponse,
    CallToAction,
    CreativeImage,
)
from core.context import auth_context
from exceptions.custom_exceptions import (
    AIProcessingException,
    BusinessValidationException,
)
from services.business_service import BusinessService
from services.session_manager import sessions
from agents.shared.genai import generate_images
from agents.shared.llm import chat_completion
from utils.prompt_loader import load_prompt
from adapters.meta.images import MetaAdImageAdapter

logger = structlog.get_logger()

STRATEGY_PROMPT = load_prompt("meta/creative_strategy.txt")
TEXT_PROMPT = load_prompt("meta/creative_text.txt")
IMAGE_INTENT_PROMPT = load_prompt("meta/image_scene.txt")

ALLOWED_CTAS = {c.value for c in CallToAction}


def _extract_json(text: str) -> str:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return text[start:end + 1]
    return text


def normalize_cta(value: str) -> str:
    if not value:
        return CallToAction.LEARN_MORE.value

    value = value.upper().strip()
    return value if value in ALLOWED_CTAS else CallToAction.LEARN_MORE.value


class MetaCreativeAgent:
    def __init__(self):
        self.business_service = BusinessService()
        self.creative_adapter = MetaCreativeAdapter()

    async def create_payload(self, session_id: str) -> CreativePayload:
        campaign_data = self._get_session_data(session_id)

        website_url = campaign_data.get("websiteURL")
        if not website_url:
            raise BusinessValidationException("Session missing websiteURL")

        ad_account_id = campaign_data.get("adAccountId")
        if not ad_account_id:
            raise BusinessValidationException("Session missing adAccountId")

        product_data = await self.business_service.process_website_data(
            website_url=website_url,
            access_token=auth_context.access_token,
            client_code=auth_context.client_code,
            x_forwarded_host=auth_context.x_forwarded_host,
            x_forwarded_port=auth_context.x_forwarded_port,
        )

        summary = product_data.final_summary
        if not summary:
            raise BusinessValidationException("Missing business summary")

        strategy_raw = await chat_completion(
            [{"role": "user", "content": STRATEGY_PROMPT.format(summary=summary)}]
        )
        strategy_json = _extract_json(strategy_raw.choices[0].message.content)
        
        # Cache summary and strategy for image generation
        sessions[session_id].setdefault("campaign_data", {})
        sessions[session_id]["campaign_data"]["business_summary"] = summary
        sessions[session_id]["campaign_data"]["visual_strategy"] = strategy_json

        text_raw = await chat_completion(
            [{"role": "user", "content": TEXT_PROMPT.format(summary=summary, strategy=strategy_json)}]
        )
        text_json = json.loads(_extract_json(text_raw.choices[0].message.content))
        text_json["cta"] = normalize_cta(text_json.get("cta"))

        try:
            payload_data = {
                "text": text_json,
            }
            creative_payload = CreativePayload(**payload_data)
        except ValidationError as e:
            logger.error(
                "Creative payload validation failed",
                error=str(e),
                raw_text=text_json,
            )
            raise AIProcessingException("Invalid creative payload from LLM")

        return creative_payload

    async def generate_image(self, session_id: str) -> CreativeImage:
        campaign_data = self._get_session_data(session_id)
        summary = campaign_data.get("business_summary")
        strategy_json = campaign_data.get("visual_strategy")
        ad_account_id = campaign_data.get("adAccountId")

        if not summary or not strategy_json:
            # If not in session, we might need to regenerate or throw error
            # For now, let's assume creative/generate was called first
            raise BusinessValidationException("Creative text must be generated before image")

        if not ad_account_id:
             raise BusinessValidationException("Session missing adAccountId")

        image_intent_raw = await chat_completion(
            [{"role": "user", "content": IMAGE_INTENT_PROMPT.format(
                summary=summary,
                visual_directive=strategy_json,
            )}]
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

        except Exception as e:
            logger.error(
                "Image generation or upload failed",
                error=str(e),
                error_type=type(e).__name__
            )
            raise AIProcessingException(f"Image generation failed: {str(e)}")

    async def create_creative(
        self, request: CreateCreativeRequest
    ) -> CreateCreativeResponse:

        page_id = os.getenv("META_PAGE_ID")
        # instagram_actor_id = os.getenv("META_INSTAGRAM_ACTOR_ID")

        if not page_id:
            raise BusinessValidationException("META_PAGE_ID not configured")
        if not request.creativePayload.image:
            raise BusinessValidationException(
                "Image required before creating creative"
            )

        if not request.creativePayload.image.image_hash:
            raise BusinessValidationException(
                "image_hash is required to create Meta creative"
            )
   

        result = await self.creative_adapter.create(
            ad_account_id=request.adAccountId,
            creative_payload=request.creativePayload.model_dump(mode="json"),
            page_id=page_id,
            # instagram_actor_id=instagram_actor_id,
        )

        return CreateCreativeResponse(creativeId=result["id"])

    def _get_session_data(self, session_id: str) -> dict[str, Any]:
        if session_id not in sessions:
            raise BusinessValidationException(f"Session not found: {session_id}")
        return sessions[session_id].get("campaign_data", {})


meta_creative_agent = MetaCreativeAgent()
