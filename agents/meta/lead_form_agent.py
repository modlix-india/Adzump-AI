import structlog
import os
import re
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

from adapters.meta.lead_forms import MetaLeadFormAdapter

from oserver.services.storage_service import StorageService
from oserver.models.storage_request_model import StorageRequest
from core.infrastructure.context import auth_context

logger = structlog.get_logger()

LEAD_FORM_PROMPT = load_prompt("meta/lead_form.txt")


class MetaLeadFormAgent:

    FIELD_MAPPING = {
        "email": "EMAIL",
        "phone_number": "PHONE",
        "full_name": "FULL_NAME",
        "first_name": "FIRST_NAME",
        "last_name": "LAST_NAME",
        "city": "CITY",
        "country": "COUNTRY",
        "company_name": "COMPANY_NAME",
        "job_title": "JOB_TITLE",
    }

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

            logger.info("Fetched site links", site_links=site_links)

            privacy_link = self._extract_privacy_policy(
                site_links,
                website_data.business_url
            )

            if privacy_link and payload.privacy_policy:
                payload.privacy_policy.link = privacy_link
            else:
                if payload.privacy_policy:
                    payload.privacy_policy.link = website_data.business_url
                    payload.privacy_policy.link_text = (
                        payload.privacy_policy.link_text or "Privacy Policy"
                    )

                logger.warning(
                    "Privacy policy URL not found, falling back to business URL",
                    session_id=session_id
                )

            return payload

        except ValidationError as e:
            logger.error("Failed to parse LLM output", error=str(e), raw=content)
            raise AIProcessingException("LLM output is not valid JSON")

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

        meta_payload = self._build_meta_lead_form_payload(payload)

        logger.info("Creating Meta lead form", payload=meta_payload)

        result = await self.lead_form_adapter.create(
            client_code=auth_context.client_code,
            page_id=page_id,
            payload=meta_payload,
        )

        return {"leadFormId": result["id"]}

    async def _fetch_site_links(self, storage_id: str):

        request = StorageRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            dataObjectId=storage_id,
            clientCode=auth_context.client_code,
        )

        response = await self.storage_service.read_storage(request)

        if not response.success or not response.content:
            logger.error("No site links found in storage", storage_id=storage_id)
            return []  

        record = response.content[0]

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

    def _sanitize_option_value(self, value: str) -> str:
        value = value.lower().replace("&", "and")
        value = re.sub(r"[^a-z0-9]+", "_", value)
        return value.strip("_")

    def _build_category_questions(self, categories):

        questions = []

        for category in categories:
            for field in category.fields:
                meta_type = self.FIELD_MAPPING.get(field)

                if meta_type:
                    questions.append({
                        "type": meta_type,
                        "key": field
                    })

        return questions

    def _build_custom_questions(self, custom_questions):

        questions = []

        for idx, q in enumerate(custom_questions):

            if not q.question:
                continue

            question = {
                "type": "CUSTOM",
                "label": q.question,
                "key": f"custom_{idx}"
            }

            if q.options:
                question["options"] = [
                    {
                        "key": self._sanitize_option_value(opt),
                        "value": opt
                    }
                    for opt in q.options
                ]

            questions.append(question)

        return questions


    def _build_meta_lead_form_payload(self, payload: LeadFormPayload) -> dict:

        questions = []

        if payload.questions:

            if payload.questions.categories:
                questions += self._build_category_questions(payload.questions.categories)

            if payload.questions.custom_questions:
                questions += self._build_custom_questions(payload.questions.custom_questions)

        meta_payload = {
            "name": payload.form_name,
            "locale": "en_US",
            "is_optimized_for_quality": True,
            "question_page_custom_headline": "Please enter the below details.",
            "questions": questions,
        }

        if payload.introduction:

            content_items = payload.introduction.list_items or []

            if not content_items and payload.introduction.paragraph:
                content_items = [payload.introduction.paragraph]

            style = "LIST_STYLE" if len(content_items) > 1 else "PARAGRAPH_STYLE"

            meta_payload["context_card"] = {
                "title": payload.introduction.headline,
                "style": style,
                "content": content_items,
            }

        if payload.privacy_policy and payload.privacy_policy.link:

            meta_payload["privacy_policy"] = {
                "url": payload.privacy_policy.link,
                "link_text": payload.privacy_policy.link_text or "Privacy Policy",
            }

        meta_payload["thank_you_page"] = {
            "title": payload.completion.headline if payload.completion else "Thank You",
            "body": payload.completion.description if payload.completion else "We will contact you soon.",
            "button_type": "VIEW_WEBSITE",
            "button_text": payload.completion.call_to_action if payload.completion else "Learn More",
            "website_url": (
                payload.completion.link
                if payload.completion and payload.completion.link
                else payload.privacy_policy.link
                if payload.privacy_policy and payload.privacy_policy.link
                else "https://example.com"
            ),
        }

        return meta_payload


meta_lead_form_agent = MetaLeadFormAgent()
