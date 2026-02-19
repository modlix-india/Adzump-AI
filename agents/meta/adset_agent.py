import asyncio
import structlog

from adapters.meta.adsets import MetaAdSetAdapter
from core.models.meta import AdSetPayload, CreateAdSetRequest, DetailedTargeting
from agents.shared.llm import chat_completion
from core.infrastructure.context import auth_context
from exceptions.custom_exceptions import (
    AIProcessingException,
    BusinessValidationException,
)
from services.business_service import BusinessService
from utils.prompt_loader import load_prompt

from adapters.meta.detailed_targeting import MetaDetailedTargetingAdapter
from adapters.meta.geo_targeting import MetaGeoTargetingAdapter

logger = structlog.get_logger()


class MetaAdSetAgent:
    def __init__(self):
        self.business_service = BusinessService()
        self.adset_adapter = MetaAdSetAdapter()
        self.targeting_adapter = MetaDetailedTargetingAdapter()
        self.geo_targeting_adapter = MetaGeoTargetingAdapter()

    async def generate_payload(self, session_id: str, ad_account_id: str) -> dict:
        website_data = await self.business_service.fetch_website_data(session_id)
        summary = website_data.final_summary or website_data.summary

        if not summary:
            raise BusinessValidationException(
                "Missing summary in product data. Please complete website analysis."
            )

        business_type = website_data.business_type or ""

        targeting = await self._generate_targeting_from_llm(
            summary=summary,
            business_type=business_type,
        )

        locales = await self._search_ad_locales(targeting.languages)

        detailed_targeting = await self._generate_detailed_targeting(summary)

        flexible_spec = await self.targeting_adapter.build_flexible_spec(
            ad_account_id=ad_account_id,
            client_code=auth_context.client_code,
            interests=detailed_targeting.interests,
            behaviors=detailed_targeting.behaviors,
            demographics=detailed_targeting.demographics,
        )

        locations = await self._build_locations(website_data=website_data)

        return {
            "genders": targeting.genders,
            "age_min": targeting.age_min,
            "age_max": targeting.age_max,
            "locales": locales,
            "flexible_spec": flexible_spec,
            "locations": locations,
        }

    # TODO: wire to API route when adset creation endpoint is added
    async def create_adset(
        self,
        create_adset_request: CreateAdSetRequest,
    ) -> dict:
        result = await self.adset_adapter.create(
            client_code=auth_context.client_code,
            ad_account_id=create_adset_request.ad_account_id,
            campaign_id=create_adset_request.campaign_id,
            meta_payload=create_adset_request.adset_payload,
        )
        return {"adsetId": result["id"]}

    async def _generate_targeting_from_llm(
        self,
        summary: str,
        business_type: str,
    ) -> AdSetPayload:
        template = load_prompt("meta/adset.txt")
        prompt = template.format(
            summary=summary,
            business_type=business_type,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a Meta Ads targeting assistant. Return ONLY valid JSON. "
                ),
            },
            {"role": "user", "content": prompt},
        ]
        response = await chat_completion(messages, model="gpt-4.1-mini")
        raw_output = response.choices[0].message.content
        if not raw_output:
            raise AIProcessingException("LLM returned empty response")
        try:
            return AdSetPayload.model_validate_json(raw_output)
        except Exception as e:
            logger.error(
                "Failed to parse AdSet LLM output",
                error=str(e),
                raw=raw_output,
            )
            raise AIProcessingException("LLM output is not valid JSON")

    async def _generate_detailed_targeting(
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
        raw_output = response.choices[0].message.content

        if not raw_output:
            raise AIProcessingException("Detailed targeting LLM returned empty response")

        try:
            return DetailedTargeting.model_validate_json(raw_output)
        except Exception as e:
            logger.error(
                "Failed to parse detailed targeting output",
                error=str(e),
                raw=raw_output,
            )
            raise AIProcessingException("Detailed targeting output invalid JSON")        

    async def _search_ad_locales(self, languages: list[str]) -> list[dict]:
        results = await asyncio.gather(
            *(
                self.adset_adapter.search_ad_locale(auth_context.client_code, lang)
                for lang in languages
            ),
            return_exceptions=True,
        )
        locales: list[dict] = []
        for language, result in zip(languages, results):
            if isinstance(result, BaseException):
                logger.warning(
                    "Failed to search locale", language=language, error=str(result)
                )
            elif isinstance(result, dict):
                locales.append(result)
        return locales

    async def _build_locations(
        self,
        website_data,
    ) -> list[dict] | None:
        if not website_data.location:
            return None

        raw_location = website_data.location.product_location
        if not raw_location:
            return None

        parts = [p.strip() for p in raw_location.split(",")]
        candidates = []

        if len(parts) >= 3:
            candidates.append(f"{parts[1]}, {parts[2]}")
            candidates.append(parts[1])
            candidates.append(parts[2])
        elif len(parts) == 2:
            candidates.append(raw_location)
            candidates.append(parts[1])
        else:
            candidates.append(raw_location)

        for location_name in candidates:
            if not location_name:
                continue

            results = await self.geo_targeting_adapter.search_locations(
                client_code=auth_context.client_code,
                location_name=location_name,
                limit=5,
            )

            if results:
                return results  # return raw list for UI

        return None


meta_adset_agent = MetaAdSetAgent()
