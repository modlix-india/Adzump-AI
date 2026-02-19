from datetime import datetime
import structlog
from pydantic import ValidationError

from adapters.meta import MetaCampaignAdapter
from core.models.meta import CampaignPayload, CreateCampaignRequest
from agents.shared.llm import chat_completion
from core.infrastructure.context import auth_context
from exceptions.custom_exceptions import AIProcessingException
from services.business_service import BusinessService
from utils.prompt_loader import load_prompt

logger = structlog.get_logger()


class MetaCampaignAgent:
    def __init__(self):
        self.business_service = BusinessService()
        self.campaign_adapter = MetaCampaignAdapter()

    async def generate_payload(self, session_id: str) -> CampaignPayload:
        response = await self.business_service.fetch_website_data(session_id)

        logger.info("Generating Meta campaign", session_id=session_id)
        return await self._generate_payload_from_llm(response.final_summary)

    async def create_campaign(
        self, create_campaign_request: CreateCampaignRequest
    ) -> dict:
        result = await self.campaign_adapter.create(
            client_code=auth_context.client_code,
            ad_account_id=create_campaign_request.ad_account_id,
            payload=create_campaign_request.campaign_payload.model_dump(),
        )
        return {"campaignId": result["id"]}

    async def _generate_payload_from_llm(self, summary: str) -> CampaignPayload:
        """Generate campaign payload using LLM."""
        template = load_prompt("meta/campaign.txt")
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
            payload = CampaignPayload.model_validate_json(content)
            payload.name = f"{payload.name} - {datetime.now().strftime('%Y-%m-%d')}"
            return payload
        except ValidationError as e:
            logger.error("Failed to parse LLM output", error=str(e), raw=content)
            raise AIProcessingException("LLM output is not valid")


# Module-level singleton - reused across all requests
meta_campaign_agent = MetaCampaignAgent()
