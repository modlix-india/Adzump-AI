import structlog
from datetime import datetime, timezone
import re
import json
from json import JSONDecodeError
from pydantic import ValidationError

from core.models.lead_form import LeadFormPayload, ThankYouPageButtonType
from services.business_service import BusinessService
from services.session_manager import sessions
from agents.shared.llm import chat_completion
from utils.prompt_loader import load_prompt
from exceptions.custom_exceptions import (
    BusinessValidationException,
    AIProcessingException,
    SessionException
)

from adapters.meta.lead_forms import MetaLeadFormAdapter

from oserver.services.storage_service import storage_service
from oserver.models.storage_request_model import StorageRequest
from core.infrastructure.context import auth_context

logger = structlog.get_logger()

LEAD_FORM_PROMPT = load_prompt("meta/lead_form.txt")

DEFAULT_COUNTRY_CODE = "IN"
DEFAULT_PHONE_PREFIX = "+91"
STORAGE_NAME = "AISuggestedData"
APP_CODE = "marketingai"


class MetaLeadFormAgent:

    def __init__(self):
        self.business_service = BusinessService()
        self.storage_service = storage_service
        self.lead_form_adapter = MetaLeadFormAdapter()

    async def generate_payload(self, session_id: str) -> LeadFormPayload:

        if session_id not in sessions:
            raise SessionException(session_id=session_id)

        website_data = await self.business_service.fetch_website_data(session_id)

        summary = website_data.final_summary or website_data.summary

        if not summary:
            raise BusinessValidationException(
                "Missing summary in product data. Please complete website analysis."
            )

        logger.info("Generating Meta lead form", session_id=session_id)

        prompt = LEAD_FORM_PROMPT.format(summary=summary, website_url=website_data.business_url)

        messages = [
            {"role": "system", "content": "You are a backend API. Always return valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        response = None
        max_retries = 2

        for attempt in range(max_retries):
            try:
                response = await chat_completion(
                    messages,
                    response_format={"type": "json_object"}
                )
                break
            except Exception as e:
                logger.warning("LLM call failed, retrying...", attempt=attempt, error=str(e))
                if attempt == max_retries - 1:
                    raise AIProcessingException("LLM call failed after retries")
        content = response.choices[0].message.content

        if not content:
            raise AIProcessingException("LLM returned empty response")

        try:
            data = json.loads(content)
        except JSONDecodeError as e:
            logger.error("Invalid JSON from LLM", error=str(e), raw=content)
            raise AIProcessingException("LLM returned invalid JSON")

        try:
            payload = LeadFormPayload.model_validate(data)
        except ValidationError as e:
            logger.error("LLM JSON structure mismatch", error=str(e), data=data)
            raise AIProcessingException("LLM returned incorrect data structure")

        base_name = (payload.name or "").strip()

        if not base_name:
            base_name = self.extract_business_name(summary, website_data.business_url)

        base_name = base_name[:25]

        now = datetime.now(timezone.utc)
        date_part = now.strftime("%d/%m/%Y")
        time_part = now.strftime("%H:%M:%S")

        payload.name = f"{base_name} {date_part} {time_part}"

        site_links = await self._fetch_site_links(website_data.storage_id)

        logger.info("Fetched site links", site_links=site_links)

        privacy_link = self._extract_privacy_policy(
            site_links,
            website_data.business_url
        )

        payload.privacy_policy.url = privacy_link or website_data.business_url

        if not privacy_link:
            logger.warning(
                "Privacy policy URL not found, falling back to business URL",
                session_id=session_id
            )

        normalized_phone = self._normalize_phone(self._extract_phone(summary))

        if normalized_phone:
            payload.thank_you_page.business_phone_number = normalized_phone
            payload.thank_you_page.button_type = ThankYouPageButtonType.CALL_BUSINESS 
            payload.thank_you_page.country_code = DEFAULT_COUNTRY_CODE

        else:
            payload.thank_you_page.button_type = ThankYouPageButtonType.VIEW_WEBSITE

        if payload.thank_you_page.button_type == ThankYouPageButtonType.VIEW_WEBSITE:
            payload.thank_you_page.website_url = website_data.business_url

        return payload

    async def create_lead_form(
        self,
        session_id: str,
        payload: LeadFormPayload,
    ) -> dict:

        if session_id not in sessions:
            raise SessionException(session_id=session_id)
        
        session = sessions[session_id]
        
        ad_plan = session.get("ad_plan") or {}

        page_id = ad_plan.get("metaPageId") or session.get("metaPageId")

        # TEMP: Hardcoded Meta page ID for development
        if not page_id:
            page_id = "332515906622723"

        if not payload.questions:
            raise BusinessValidationException("At least one question is required")

        if not payload.name:
            raise BusinessValidationException("Form name is required")    
             
        logger.info("Final Lead Form Name", name=payload.name)

        meta_payload = payload.model_dump(exclude_none=True)

        logger.info("Creating Meta lead form", payload=meta_payload)

        result = await self.lead_form_adapter.create(
            client_code=auth_context.client_code,
            page_id=page_id,
            payload=meta_payload,
        )

        return {"leadFormId": result["id"]}

    async def _fetch_site_links(self, storage_id: str):

        if not storage_id:
            logger.warning("Storage ID is None, skipping site link fetch")
            return []

        request = StorageRequest(
            storageName=STORAGE_NAME,
            appCode=APP_CODE,
            dataObjectId=storage_id,
            clientCode=auth_context.client_code,
        )

        response = await self.storage_service.read_storage(request)

        if not response.success or not response.content:
            logger.error("No site links found in storage", storage_id=storage_id)
            return []  

        record = response.content[0]
        return record.get("siteLinks", [])

    def _extract_privacy_policy(self, links, base_url):

        if not links or not base_url:
            return None

        for link in links:
            href = (link.get("href") or "").strip()
            text = (link.get("text") or "").lower()

            if not href or href == "#":
                continue

            if "privacy" in href.lower() or "privacy" in text:
                return href if href.startswith("http") else f"{base_url.rstrip('/')}/{href.lstrip('/')}"

        for link in links:
            href = (link.get("href") or "").strip()
            text = (link.get("text") or "").lower()

            if not href or href == "#":
                continue

            if any(k in href.lower() or k in text for k in ["policy", "terms", "legal"]):
                return href if href.startswith("http") else f"{base_url.rstrip('/')}/{href.lstrip('/')}"

        return None        

    def _extract_phone(self, text: str) -> str | None:
        matches = re.findall(r'\+\d[\d\s\-\(\)]{7,15}', text)
        if matches:
            return matches[0]

        matches = re.findall(r'\b(?:\d[\s\-\(\)]*){10,12}\b', text)
        if matches:
            return max(matches, key=len)

        return None

    def _normalize_phone(self, phone: str | None) -> str | None:
        if not phone:
            return None

        phone = re.sub(r"[^\d+]", "", phone)

        if phone.startswith("+"):
            return phone

        if phone.isdigit() and len(phone[-10:]) == 10:
            return DEFAULT_PHONE_PREFIX + phone[-10:]

        return None

    def extract_business_name(self, summary: str, website_url: str) -> str:

        if website_url:
            domain = website_url.replace("https://", "").replace("http://", "").split("/")[0]
            return domain.split(".")[0].title()

        return "LeadForm"    


meta_lead_form_agent = MetaLeadFormAgent()
