import structlog
from pydantic import ValidationError

from core.models.meta import LeadFormPayload
from services.business_service import BusinessService
from services.session_manager import sessions
from agents.shared.llm import chat_completion
from utils.prompt_loader import load_prompt
from exceptions.custom_exceptions import (
    BusinessValidationException,
    AIProcessingException,
)

from oserver.services.storage_service import StorageService
from oserver.models.storage_request_model import StorageRequest
from core.infrastructure.context import auth_context

logger = structlog.get_logger()

LEAD_FORM_PROMPT = load_prompt("meta/lead_form.txt")


class MetaLeadFormAgent:
    def __init__(self):
        self.business_service = BusinessService()
        self.storage_service = StorageService()

    async def generate_payload(self, session_id: str) -> LeadFormPayload:

        if session_id not in sessions:
            raise BusinessValidationException("Session not found")
            
        website_data = await self.business_service.fetch_website_data(session_id)

        summary = website_data.final_summary or website_data.summary

        if not summary:
            raise BusinessValidationException(
                "Missing summary in product data. Please complete website analysis."
            )

        logger.info("Generating Meta lead form", session_id=session_id)

        prompt = LEAD_FORM_PROMPT.format(summary=summary)

        messages = [
            {"role": "system", "content": "You are a backend API. Always return valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        response = await chat_completion(messages)
        content = response.choices[0].message.content

        if not content:
            raise AIProcessingException("LLM returned empty response")

        try:
            payload = LeadFormPayload.model_validate_json(content)

            site_links = await self._fetch_site_links(website_data.storage_id)

            privacy_link = self._extract_privacy_policy(
                site_links,
                website_data.business_url
            )

            if privacy_link and payload.privacy_policy:
                payload.privacy_policy.link = privacy_link
            else:
                if payload.privacy_policy:
                    payload.privacy_policy.link = None
                    payload.privacy_policy.link_text = None
                    
                logger.warning(
                    "Privacy policy URL not found",
                    session_id=session_id
                )        

            return payload

        except ValidationError as e:
            logger.error("Failed to parse LLM output", error=str(e), raw=content)
            raise AIProcessingException("LLM output is not valid JSON")


    async def _fetch_site_links(self, storage_id: str):

        request = StorageRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            dataObjectId=storage_id,
            clientCode=auth_context.client_code,
        )
        response = await self.storage_service.read_storage(request)

        if not response.success:
            logger.error(
                "Failed to fetch site links",
                error=response.error,
            )
            return []   
        data = response.result

        try:
            if isinstance(data, dict):
                return data.get("siteLinks", [])

            if isinstance(data, list) and len(data) > 0:
                return data[0].get("result", {}).get("result", {}).get("siteLinks", [])

        except Exception:
            pass

        return []

    def _extract_privacy_policy(self, links, base_url):

        if not links:
            return None

        for link in links:
            href = (link.get("href") or "").strip()
            text = (link.get("text") or "").lower()

            if "privacy" in href.lower() or "privacy" in text:
                return href if href.startswith("http") else f"{base_url.rstrip('/')}/{href.lstrip('/')}"

        for link in links:
            href = (link.get("href") or "").strip()
            text = (link.get("text") or "").lower()

            if any(k in href.lower() or k in text for k in ["policy", "terms", "legal"]):
                return href if href.startswith("http") else f"{base_url.rstrip('/')}/{href.lstrip('/')}"

        return None


meta_lead_form_agent = MetaLeadFormAgent()
