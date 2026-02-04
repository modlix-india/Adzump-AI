import json
import os
import structlog

from adapters.meta.adsets import MetaAdSetAdapter
from adapters.meta.adset_targeting import build_meta_targeting
from adapters.meta.models.adset_model import (
    AdSetSuggestion,
    CreateAdSetRequest,
    CreateAdSetResponse,
    GenerateAdSetResponse,
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
        goal: str,
        region: str,
        ad_account_id: str,
    ) -> GenerateAdSetResponse:
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

        llm_suggestion = await self._generate_payload_from_llm(
            summary=summary,
            goal=goal,
            region=region,
        )

        meta_token = os.getenv("META_ACCESS_TOKEN", "")

        meta_targeting = await build_meta_targeting(
            llm_output=llm_suggestion.model_dump(mode="json"),
            ad_account_id=ad_account_id.removeprefix("act_"),
            access_token=meta_token,
            region=region,
        )

        meta_targeting["daily_budget"] = llm_suggestion.daily_budget

        return GenerateAdSetResponse(
            adset_name=llm_suggestion.adset_name,
            human_targeting=llm_suggestion,
            meta_targeting=meta_targeting,
        )

    async def create_adset(
        self,
        create_adset_request: CreateAdSetRequest,
    ) -> CreateAdSetResponse:
        result = await self.adset_adapter.create(
            ad_account_id=create_adset_request.ad_account_id,
            campaign_id=create_adset_request.campaign_id,
            payload=create_adset_request.adset_payload,
        )

        return CreateAdSetResponse(adsetId=result["id"])

    async def _generate_payload_from_llm(
        self,
        summary: str,
        goal: str,
        region: str,
    ) -> AdSetSuggestion:
        template = load_prompt("meta/adset.txt")
        prompt = template.format(
            summary=summary,
            goal=goal,
            region=region,
        )

        messages = [
            {"role": "system", "content": "Respond only with valid JSON"},
            {"role": "user", "content": prompt},
        ]

        response = await chat_completion(messages)
        content = response.choices[0].message.content

        if not content:
            raise AIProcessingException("LLM returned empty response")

        try:
            return AdSetSuggestion.model_validate_json(content)
        except Exception as e:
            logger.error("Failed to parse AdSet LLM output", error=str(e), raw=content)
            raise AIProcessingException("LLM output is not valid JSON")


meta_adset_agent = MetaAdSetAgent()
