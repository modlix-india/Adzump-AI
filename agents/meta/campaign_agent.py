from datetime import datetime
from typing import Any

import structlog
from pydantic import ValidationError

from adapters.meta import MetaCampaignAdapter
from adapters.meta.models.campaign_model import (
    CampaignPayload,
    CreateCampaignRequest,
    CreateCampaignResponse,
)
from agents.shared.llm import chat_completion
from core.context import auth_context
from exceptions.custom_exceptions import (
    AIProcessingException,
    BusinessValidationException,
)
from services.business_service import BusinessService
from services.session_manager import sessions
from utils.prompt_loader import load_prompt

logger = structlog.get_logger()


class MetaCampaignAgent:
    def __init__(self):
        self.business_service = BusinessService()
        self.campaign_adapter = MetaCampaignAdapter()

    async def create_payload(self, session_id: str) -> CampaignPayload:
        campaign_data = self._get_session_data(session_id)
        website_url = campaign_data.get("websiteURL")
        if not website_url:
            raise BusinessValidationException("Session missing websiteURL")

        response = await self.business_service.process_website_data(
            website_url=website_url,
            access_token=auth_context.access_token,
            client_code=auth_context.client_code,
            x_forwarded_host=auth_context.x_forwarded_host,
            x_forwarded_port=auth_context.x_forwarded_port,
        )

        logger.info("Generating Meta campaign", session_id=session_id)
        return await self._generate_payload_from_llm(response.final_summary)

    async def create_campaign(
        self, create_campaign_request: CreateCampaignRequest
    ) -> CreateCampaignResponse:
        result = await self.campaign_adapter.create(
            create_campaign_request.ad_account_id,
            create_campaign_request.campaign_payload.model_dump(),
        )
        return CreateCampaignResponse(campaignId=result["id"])

    def _get_session_data(self, session_id: str) -> dict[str, Any]:
        if session_id not in sessions:
            raise BusinessValidationException(f"Session not found: {session_id}")

        session = sessions[session_id]
        return session.get("campaign_data", {})

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
