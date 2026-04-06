import structlog
from datetime import datetime
import re
import json
from pydantic import ValidationError

from core.models.lead_form import LeadFormPayload
from services.business_service import BusinessService
from services.session_manager import sessions
from agents.shared.llm import chat_completion
from utils.prompt_loader import load_prompt
from exceptions.custom_exceptions import (
    BusinessValidationException,
    AIProcessingException,
)

from adapters.meta.lead_forms import MetaLeadFormAdapter

from oserver.services.storage_service import StorageService
from oserver.models.storage_request_model import StorageRequest
from core.infrastructure.context import auth_context

logger = structlog.get_logger()

LEAD_FORM_PROMPT = load_prompt("meta/lead_form.txt")


class MetaLeadFormAgent:

    def __init__(self):
        self.business_service = BusinessService()
        self.storage_service = StorageService()
        self.lead_form_adapter = MetaLeadFormAdapter()

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

        prompt = LEAD_FORM_PROMPT.format(summary=summary, website_url=website_data.business_url)

        messages = [
            {"role": "system", "content": "You are a backend API. Always return valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        response = await chat_completion(messages)
        content = response.choices[0].message.content

        if not content:
            raise AIProcessingException("LLM returned empty response")

        try:
            data = json.loads(content)

            if "name" in data and len(data["name"]) > 50:
                data["name"] = data["name"][:50]
                data["name"] = re.sub(r'\s+\S*$', '', data["name"])

            payload = LeadFormPayload.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse LLM output", error=str(e), raw=content)
            raise AIProcessingException("LLM output is not valid JSON")

        site_links = await self._fetch_site_links(website_data.storage_id)

        logger.info("Fetched site links", site_links=site_links)

        privacy_link = self._extract_privacy_policy(
            site_links,
            website_data.business_url
        )

        payload.privacy_policy.url = (
            privacy_link if privacy_link else website_data.business_url
        )

        if not privacy_link:
            logger.warning(
                "Privacy policy URL not found, falling back to business URL",
                session_id=session_id
            )

        phone = self._extract_phone(summary)
        phone = self._normalize_phone(phone)

        if phone:
            payload.thank_you_page.business_phone_number = phone
            payload.thank_you_page.button_type = "CALL_BUSINESS"  
            payload.thank_you_page.country_code = "IN" 

        else:
            payload.thank_you_page.button_type = "VIEW_WEBSITE"

        if payload.thank_you_page.button_type == "VIEW_WEBSITE":
            payload.thank_you_page.website_url = website_data.business_url

        return payload

    async def create_lead_form(
        self,
        session_id: str,
        payload: LeadFormPayload,
    ) -> dict:

        session = sessions.get(session_id)
        if not session:
            raise BusinessValidationException("Session not found")
        
        ad_plan = session.get("ad_plan") or {}

        page_id = ad_plan.get("metaPageId") or session.get("metaPageId")

        # TEMP: Hardcoded Meta page ID for development
        if not page_id:
            page_id = "332515906622723"

        if not payload.questions:
            raise BusinessValidationException("At least one question is required")

        if not payload.name:
            raise BusinessValidationException("Form name is required")    

        clean_name = re.sub(r'[^a-zA-Z0-9 ]', '', payload.name)
        clean_name = re.sub(r'\s+', ' ', clean_name).strip()

        now = datetime.now()
        date_part = now.strftime("%d%b")   
        time_part = now.strftime("%H%M%S")    
        payload.name = f"{clean_name[:30]}_{date_part}_{time_part}"    

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
            storageName="AISuggestedData",
            appCode="marketingai",
            dataObjectId=storage_id,
            clientCode=auth_context.client_code,
        )

        response = await self.storage_service.read_storage(request)

        if not response.success or not response.result:
            logger.error("No site links found in storage", storage_id=storage_id)
            return []  

        record = response.result

        if isinstance(record, list) and len(record) > 0:
            record = record[0]

        data = record.get("result", {})

        while isinstance(data, dict) and "result" in data:
            data = data["result"]

        site_links = data.get("siteLinks", [])

        return site_links 

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

        if phone.startswith("+91"):
            return phone

        if phone.startswith("+"):
            phone = phone.lstrip("+")

        if phone.startswith("0"):
            phone = phone[1:]

        if phone.isdigit():
            return "+91" + phone[-10:]

        return None


meta_lead_form_agent = MetaLeadFormAgent()
