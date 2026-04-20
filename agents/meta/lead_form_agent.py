import structlog
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re
import json
from json import JSONDecodeError
from pydantic import ValidationError
from core.models.lead_form import (
    LeadFormPayload,
    ThankYouPageButtonType,
    QuestionType,
    LeadFormCreateResponse,
)
from services.business_service import BusinessService
from services.session_manager import sessions
from agents.shared.llm import chat_completion
from utils.prompt_loader import load_prompt
from exceptions.custom_exceptions import (
    BusinessValidationException,
    AIProcessingException,
    SessionException,
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
MAX_LLM_RETRIES = 3
MAX_BRAND_NAME_LENGTH = 25


class MetaLeadFormAgent:
    def __init__(self):
        self.business_service = BusinessService()
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

        logger.info(
            "Generating Meta lead form",
            session_id=session_id,
            client_code=auth_context.client_code,
        )

        payload = await self._get_lead_form_from_llm(summary, website_data.business_url)

        self._apply_timestamped_name(payload, summary, website_data.business_url)

        await self._apply_privacy_policy(payload, website_data, session_id)

        self._set_thank_you_page_config(payload, summary, website_data.business_url)

        return payload

    async def _get_lead_form_from_llm(
        self, summary: str, website_url: str
    ) -> LeadFormPayload:
        question_mapping_str = "\n".join(
            f"{q.name.lower()} → {q.value}"
            for q in QuestionType
            if q != QuestionType.CUSTOM
        )

        button_types_str = "\n".join(bt.value for bt in ThankYouPageButtonType)

        prompt = LEAD_FORM_PROMPT.format(
            summary=summary,
            website_url=website_url,
            question_mapping=question_mapping_str,
            button_types=button_types_str,
        )

        messages = [
            {
                "role": "system",
                "content": "You are a backend API. Always return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ]

        max_retries = MAX_LLM_RETRIES
        content = None

        for attempt in range(max_retries):
            try:
                response = await chat_completion(
                    messages, response_format={"type": "json_object"}
                )
                content = response.choices[0].message.content

                if not content:
                    raise AIProcessingException("LLM returned empty response")

                data = json.loads(content)
                payload = LeadFormPayload.model_validate(data)

                if (
                    not payload.question_page_custom_headline
                    or not payload.question_page_custom_headline.strip()
                ):
                    payload.question_page_custom_headline = "Share your details"

                if payload.enable_otp_verification:
                    if not payload.is_optimized_for_quality:
                        payload.enable_otp_verification = False
                    else:
                        has_phone = any(
                            q.type == QuestionType.PHONE for q in payload.questions
                        )
                        if not has_phone:
                            payload.enable_otp_verification = False

                return payload

            except (JSONDecodeError, ValidationError) as e:
                logger.warning(
                    "LLM validation failed, retrying...",
                    attempt=attempt,
                    error=str(e),
                )
                if attempt == max_retries - 1:
                    raise AIProcessingException(
                        f"LLM call failed after retries: {str(e)}"
                    )

                messages.append({"role": "assistant", "content": content or "{}"})
                messages.append(
                    {
                        "role": "user",
                        "content": f"Your last response failed validation with this error: {str(e)}. Please fix the JSON structure to satisfy the schema.",
                    }
                )

    def _apply_timestamped_name(
        self, payload: LeadFormPayload, summary: str, website_url: str
    ):
        base_name = (payload.name or "").strip()

        if not base_name:
            base_name = self.get_fallback_business_name(summary, website_url)

        base_name = base_name[:MAX_BRAND_NAME_LENGTH]

        try:
            tz = ZoneInfo(auth_context.timezone)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("Asia/Kolkata")

        now = datetime.now(tz)
        date_part = now.strftime("%d/%m/%Y")
        time_part = now.strftime("%H:%M:%S")

        payload.name = f"{base_name} {date_part} {time_part}"

    async def _apply_privacy_policy(
        self, payload: LeadFormPayload, website_data, session_id: str
    ):
        site_links = await self._fetch_site_links(website_data.storage_id)
        logger.info("Fetched site links", site_links=site_links)

        privacy_link = self._extract_privacy_policy(
            site_links, website_data.business_url
        )

        payload.privacy_policy.url = privacy_link or website_data.business_url

        if not privacy_link:
            logger.warning(
                "Privacy policy URL not found, falling back to business URL",
                session_id=session_id,
            )

    def _set_thank_you_page_config(
        self, payload: LeadFormPayload, summary: str, business_url: str
    ):
        phone = payload.thank_you_page.business_phone_number
        if phone:
            phone = phone.strip()
        normalized_phone = self._normalize_phone(phone)

        if payload.thank_you_page.button_type == ThankYouPageButtonType.CALL_BUSINESS:
            if normalized_phone:
                payload.thank_you_page.business_phone_number = normalized_phone
                payload.thank_you_page.country_code = DEFAULT_COUNTRY_CODE
                payload.thank_you_page.website_url = None
                payload.thank_you_page.button_text = (
                    payload.thank_you_page.button_text or "Call Now"
                )
            else:
                logger.warning(
                    "LLM requested CALL_BUSINESS but phone is missing or invalid. Falling back to VIEW_WEBSITE."
                )
                payload.thank_you_page.button_type = ThankYouPageButtonType.VIEW_WEBSITE
                payload.thank_you_page.website_url = business_url
                payload.thank_you_page.button_text = "Visit Website"
                payload.thank_you_page.business_phone_number = None
                payload.thank_you_page.country_code = None

        elif payload.thank_you_page.button_type == ThankYouPageButtonType.VIEW_WEBSITE:
            payload.thank_you_page.website_url = business_url
            payload.thank_you_page.button_text = "Visit Website"
            payload.thank_you_page.business_phone_number = None
            payload.thank_you_page.country_code = None

        return payload

    async def create_lead_form(
        self,
        session_id: str,
        payload: LeadFormPayload,
    ) -> LeadFormCreateResponse:

        if session_id not in sessions:
            raise SessionException(session_id=session_id)

        session = sessions[session_id]

        ad_plan = session.get("ad_plan") or {}

        page_id = ad_plan.get("metaPageId") or session.get("metaPageId")

        # TODO: Transition from hardcoded fallback to robust error handling or dynamic retrieval.
        # This ID (332515906622723) is a temporary placeholder for development/testing.
        if not page_id:
            page_id = "332515906622723"

        enable_otp = payload.enable_otp_verification
        is_optimized = payload.is_optimized_for_quality

        is_phone_sms_verify_enabled = enable_otp and is_optimized

        has_phone = any(q.type == QuestionType.PHONE for q in payload.questions)

        if enable_otp and not has_phone:
            logger.warning(
                "OTP verification enabled but no PHONE field found. "
                "Meta will likely ignore is_phone_sms_verify_enabled."
            )

        logger.info(
            "Creating Meta lead form",
            name=payload.name,
            is_optimized_for_quality=is_optimized,
            is_phone_sms_verify_enabled=is_phone_sms_verify_enabled,
            has_phone_field=has_phone,
            client_code=auth_context.client_code,
        )

        meta_payload = payload.model_dump(
            exclude_none=True, exclude={"enable_otp_verification"}
        )

        meta_payload["is_phone_sms_verify_enabled"] = is_phone_sms_verify_enabled

        result = await self.lead_form_adapter.create(
            client_code=auth_context.client_code,
            page_id=page_id,
            payload=meta_payload,
        )

        return LeadFormCreateResponse(leadFormId=result["id"])

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

        response = await storage_service.read_storage(request)

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
                return (
                    href
                    if href.startswith("http")
                    else f"{base_url.rstrip('/')}/{href.lstrip('/')}"
                )

        for link in links:
            href = (link.get("href") or "").strip()
            text = (link.get("text") or "").lower()

            if not href or href == "#":
                continue

            if any(
                k in href.lower() or k in text for k in ["policy", "terms", "legal"]
            ):
                return (
                    href
                    if href.startswith("http")
                    else f"{base_url.rstrip('/')}/{href.lstrip('/')}"
                )

        return None

    def _normalize_phone(self, phone: str | None) -> str | None:
        if not phone:
            return None

        phone = re.sub(r"[^\d+]", "", phone)

        if phone.startswith("+91") and len(phone) == 13:
            if phone[3] in "6789":
                return phone
            return None

        digits = re.sub(r"\D", "", phone)
        if len(digits) == 10 and digits[0] in "6789":
            return "+91" + digits

        return None

    def get_fallback_business_name(self, summary: str, website_url: str) -> str:

        if website_url:
            domain = (
                website_url.replace("https://", "").replace("http://", "").split("/")[0]
            )
            return domain.split(".")[0].title()

        return "LeadForm"


meta_lead_form_agent = MetaLeadFormAgent()
