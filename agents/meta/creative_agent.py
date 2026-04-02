from typing import Any, List
import json
import os
import base64
import httpx

import structlog
from pydantic import ValidationError

from adapters.meta.creatives import MetaCreativeAdapter
from core.models.meta import (
    CreativePayload,
    CreateCreativeRequest,
    CreateCreativeResponse,
    CallToAction,
    CreativeImage,
    UnifiedPosterRequest,
)
from exceptions.custom_exceptions import (
    AIProcessingException,
    BusinessValidationException,
)
from services.business_service import BusinessService
from services.session_manager import sessions
from adapters.gemini.client import generate_images
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
        return text[start : end + 1]
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

    async def generate_payload(self, session_id: str) -> CreativePayload:

        if session_id not in sessions:
            raise BusinessValidationException("Session not found")

        website_data = await self.business_service.fetch_website_data(session_id)

        summary = website_data.final_summary or website_data.summary

        if not summary:
            raise BusinessValidationException(
                "Missing summary in product data. Please complete website analysis."
            )

        strategy_raw = await chat_completion(
            [{"role": "user", "content": STRATEGY_PROMPT.format(summary=summary)}]
        )
        strategy_json = _extract_json(strategy_raw.choices[0].message.content)

        # Cache summary and strategy for image generation
        sessions[session_id].setdefault("campaign_data", {})
        sessions[session_id]["campaign_data"]["business_summary"] = summary
        sessions[session_id]["campaign_data"]["visual_strategy"] = strategy_json

        text_raw = await chat_completion(
            [
                {
                    "role": "user",
                    "content": TEXT_PROMPT.format(
                        summary=summary, strategy=strategy_json
                    ),
                }
            ]
        )
        text_json = json.loads(_extract_json(text_raw.choices[0].message.content))
        text_json["cta"] = normalize_cta(text_json.get("cta"))

        try:
            creative_payload = CreativePayload(text=text_json)
        except ValidationError as e:
            logger.error(
                "Creative payload validation failed",
                error=str(e),
                raw_text=text_json,
            )
            raise AIProcessingException("Invalid creative payload from LLM")

        return creative_payload

    async def generate_image(
        self,
        request: UnifiedPosterRequest,
    ) -> CreativeImage:

        logger.info(
            "Generating image generation intent (stateless)",
            summary=request.summary,
            headline=request.headline,
        )

        # 1. Download Logo if provided (Multimodal Phase)
        image_parts: List[bytes] = []
        if request.logo_url:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    logo_resp = await client.get(request.logo_url)
                    if logo_resp.status_code == 200:
                        image_parts.append(logo_resp.content)
                        logger.info(
                            "Logo downloaded for multimodal generation",
                            url=request.logo_url,
                        )
            except Exception as e:
                logger.warning(
                    "Failed to download logo, proceeding without it", error=str(e)
                )

        # 2. Build Conditional Brand Instructions
        brand_instructions = ""
        if request.logo_url:
            brand_instructions += "\n- LOGO: Incorporate the logo from the provided reference image. Place it professionally (e.g., bottom corner)."
        if request.primary_color:
            brand_instructions += f"\n- PRIMARY COLOR: Use {request.primary_color} for the main CTA button and bold headline elements."
        if request.secondary_color:
            brand_instructions += f"\n- SECONDARY COLOR: Use {request.secondary_color} for subheadings or subtle accents."
        if request.font_family:
            brand_instructions += f"\n- FONT STYLE: Render text using a look and feel consistent with the '{request.font_family}' typeface."

        # 3. First Pass: Use a Text Model (Strategist) to generate a narrative scene prompt
        # This pass handles the strategy, layout reasoning, and copy orchestration
        PROMPT_PATH = "prompts/meta/image_scene.txt"
        try:
            with open(PROMPT_PATH, "r") as f:
                template = f.read()

            strategist_input = template.format(
                summary=request.summary,
                headline=request.headline,
                description=request.description,
                cta=request.cta,
                brand_instructions=brand_instructions,
            )

            logger.info("Requesting narrative scene refinement from Strategist LLM")
            strategist_resp = await chat_completion(
                messages=[{"role": "user", "content": strategist_input}]
            )
            refined_scene_prompt = strategist_resp.choices[0].message.content.strip()

            # Log the refined prompt clearly for debug
            logger.info(
                "STRATEGIST REFINED PROMPT", refined_prompt=refined_scene_prompt
            )

        except Exception as e:
            logger.error("Failed to load or refine prompt template", error=str(e))
            raise AIProcessingException(f"Prompt preparation failed: {str(e)}")

        # 4. Second Pass: Use the Image Model (Renderer) to generate the actual pixels
        try:
            # We pass the refined narrative AND any reference images (Logo) to Gemini 2.5
            images = await generate_images(
                refined_scene_prompt,
                n=1,
                aspect_ratio=request.aspect_ratio,
                image_parts=image_parts,
            )
            if not images:
                raise AIProcessingException("Image generation returned empty results")

            image_base64 = base64.b64encode(images[0]).decode("utf-8")
            image_adapter = MetaAdImageAdapter()

            upload_result = await image_adapter.upload_image(
                ad_account_id=request.ad_account_id,
                image_base64=image_base64,
            )

            image_data = next(iter(upload_result["images"].values()))
            image_hash = image_data["hash"]
            image_url = image_data.get("url")

            image_adapter = MetaAdImageAdapter()

            # Fallback: if upload response didn't include URL, fetch it explicitly
            if not image_url:
                logger.info(
                    "Retrying to fetch Meta URL for hash", image_hash=image_hash
                )
                image_url = await image_adapter.get_image_url(
                    ad_account_id=request.ad_account_id, image_hash=image_hash
                )

            logger.info(
                "Stateless Meta creative image saved",
                image_hash=image_hash,
                image_url=image_url,
            )
            return CreativeImage(image_hash=image_hash, image_url=image_url)

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

        page_id = os.getenv("META_PAGE_ID")

        if not page_id:
            raise BusinessValidationException("META_PAGE_ID not configured")
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
