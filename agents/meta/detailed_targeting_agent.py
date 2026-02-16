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
from services.business_service import BusinessService
from services.session_manager import sessions
from utils.prompt_loader import load_prompt

logger = structlog.get_logger()


class MetaDetailedTargetingAgent:
    def __init__(self):
        self.business_service = BusinessService()
        self.targeting_adapter = MetaDetailedTargetingAdapter()

    async def create_payload(
        self,
        session_id: str,
        ad_account_id: str,
    ) -> dict:

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

        logger.info(
            "Generating Meta detailed targeting",
            session_id=session_id,
        )

        llm_payload = await self._generate_payload_from_llm(
            response.final_summary
        )

        flexible_spec = await self.targeting_adapter.build_flexible_spec(
            ad_account_id=ad_account_id,
            interests=llm_payload.interests,
            behaviors=llm_payload.behaviors,
            demographics=llm_payload.demographics,
        )

        return {
            "flexible_spec": flexible_spec
        }

    def _get_session_data(self, session_id: str) -> dict:
        if session_id not in sessions:
            raise BusinessValidationException(f"Session not found: {session_id}")

        session = sessions[session_id]
        return session.get("campaign_data", {})

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
