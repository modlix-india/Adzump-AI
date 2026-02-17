import structlog
from pydantic import ValidationError

from adapters.meta.models.detailed_targeting_model import DetailedTargeting
from adapters.meta.detailed_targeting import MetaDetailedTargetingAdapter
from agents.shared.llm import chat_completion
from core.context import auth_context
from exceptions.custom_exceptions import (
    AIProcessingException,
    BusinessValidationException,
)
from oserver.models.storage_request_model import (
    StorageFilter,
    StorageReadRequest,
)
from oserver.services.storage_service import StorageService
from utils.prompt_loader import load_prompt
from utils.helpers import normalize_url

logger = structlog.get_logger()


class MetaDetailedTargetingAgent:
    def __init__(self):
        self.targeting_adapter = MetaDetailedTargetingAdapter()

    async def create_payload(
        self,
        website_url: str,
        ad_account_id: str,
    ) -> dict:

        website_url = normalize_url(website_url)

        logger.info(
            "Generating Meta detailed targeting",
            website_url=website_url,
        )

        final_summary = await self._get_final_summary_from_storage(website_url)

        llm_payload = await self._generate_payload_from_llm(final_summary)

        flexible_spec = await self.targeting_adapter.build_flexible_spec(
            ad_account_id=ad_account_id,
            interests=llm_payload.interests,
            behaviors=llm_payload.behaviors,
            demographics=llm_payload.demographics,
        )

        return {"flexible_spec": flexible_spec}

    async def _get_final_summary_from_storage(self, website_url: str) -> str:

        storage_service = StorageService(
            access_token=auth_context.access_token,
            client_code=auth_context.client_code,
            x_forwarded_host=auth_context.x_forwarded_host,
            x_forwarded_port=auth_context.x_forwarded_port,
        )

        website_url = normalize_url(website_url)

        logger.info("Fetching summary from storage", website_url=website_url)

        read_request = StorageReadRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            clientCode=auth_context.client_code,
            filter=StorageFilter(field="businessUrl", value=website_url),
        )

        response = await storage_service.read_page_storage(read_request)
       

        if not response.success:
            raise BusinessValidationException("Failed to read business data")

        try:
            records = (
                response.result[0]
                .get("result", {})
                .get("result", {})
                .get("content", [])
            )
        except Exception:
            records = []

        if not records:
            raise BusinessValidationException(
                "No business summary found. Please generate summary first."
            )

        final_summary = records[-1].get("finalSummary")

        if not final_summary or not final_summary.strip():
            raise BusinessValidationException(
                "Business summary is empty. Please regenerate summary."
            )

        return final_summary



    async def _generate_payload_from_llm(
        self,
        summary: str,
    ) -> DetailedTargeting:

        template = load_prompt("meta/detailed_targeting.txt")
        prompt = template.format(summary=summary)

        messages = [
            {"role": "system", "content": "Respond only with valid JSON"},
            {"role": "user", "content": prompt},
        ]

        response = await chat_completion(messages)
        content = response.choices[0].message.content

        if not content:
            raise AIProcessingException("LLM returned empty response")

        try:
            return DetailedTargeting.model_validate_json(content)
        except ValidationError as e:
            logger.error(
                "Failed to parse LLM targeting output",
                error=str(e),
                raw=content,
            )
            raise AIProcessingException("LLM output is not valid")


meta_detailed_targeting_agent = MetaDetailedTargetingAgent()
