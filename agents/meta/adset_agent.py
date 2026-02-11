import structlog
from typing import List
import json

from adapters.meta.adsets import MetaAdSetAdapter
from adapters.meta.models.adset_model import (
    AdSetSuggestion,
    CreateAdSetRequest,
    CreateAdSetResponse,
)
from agents.shared.llm import chat_completion
from core.context import auth_context
from exceptions.custom_exceptions import (
    AIProcessingException,
    BusinessValidationException,
)
from services.business_service import BusinessService
from utils.prompt_loader import load_prompt

logger = structlog.get_logger()


class MetaAdSetAgent:
    def __init__(self):
        self.business_service = BusinessService()
        self.adset_adapter = MetaAdSetAdapter()

    async def create_payload(
        self,
        data_object_id: str,
        ad_account_id: str,
    ) -> dict:
        product_data = await self.business_service.fetch_product_details(
            data_object_id=data_object_id,
            access_token=auth_context.access_token,
            client_code=auth_context.client_code,
            x_forwarded_host=auth_context.x_forwarded_host,
            x_forwarded_port=auth_context.x_forwarded_port,
        )

        summary = product_data.get("summary") or product_data.get("finalSummary")
        if not summary:
            raise BusinessValidationException(
                "Missing summary in product data. Please complete website analysis."
            )

        meta_locales = await self.adset_adapter.fetch_available_languages()

        available_locales = [
            {"id": locale["id"], "name": locale["name"]}
            for locale in meta_locales
        ]

        llm_output = await self._generate_payload_from_llm(
            summary=summary,
            available_locales=available_locales,
        )
        return llm_output.model_dump(mode="json")

    async def _generate_payload_from_llm(
        self,
        summary: str,
        available_locales: List[dict],
    ) -> AdSetSuggestion:
        template = load_prompt("meta/adset.txt")
        prompt = template.format(
            summary=summary,
            available_locales=json.dumps(available_locales, indent=2),
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a Meta Ads targeting assistant. "
                    "Return ONLY valid JSON. "
                    "Choose locale IDs ONLY from the provided list. "
                    "Do NOT invent locale IDs or language names."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        response = await chat_completion(messages)
        content = response.choices[0].message.content

        if not content:
            raise AIProcessingException("LLM returned empty response")

        try:
            return AdSetSuggestion.model_validate_json(content)
        except Exception as e:
            logger.error(
                "Failed to parse AdSet LLM output",
                error=str(e),
                raw=content,
            )
            raise AIProcessingException("LLM output is not valid JSON")

    async def create_adset(
        self,
        create_adset_request: CreateAdSetRequest,
    ) -> CreateAdSetResponse:
        result = await self.adset_adapter.create(
            ad_account_id=create_adset_request.ad_account_id,
            campaign_id=create_adset_request.campaign_id,
            meta_payload=create_adset_request.adset_payload,
        )

        return CreateAdSetResponse(adsetId=result["id"])


meta_adset_agent = MetaAdSetAgent()
