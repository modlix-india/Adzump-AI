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

from pydantic import ValidationError

from adapters.meta.detailed_targeting import MetaDetailedTargetingAdapter
from adapters.meta.geo_targeting import MetaGeoTargetingAdapter

from oserver.models.storage_request_model import StorageRequest
from oserver.services.storage_service import StorageService

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

        suggested_geo_targets = getattr(website_data, "suggested_geo_targets", None)

        if not suggested_geo_targets and getattr(website_data, "storage_id", None):
            suggested_geo_targets = await self._fetch_suggested_geo_targets(
                website_data.storage_id
            )

        allowed_countries = getattr(website_data, "special_ad_category_country", None)
        if allowed_countries and isinstance(allowed_countries, str):
            allowed_countries = [allowed_countries]

        locations = await self._build_locations(
            suggested_geo_targets=suggested_geo_targets,
            allowed_countries=allowed_countries,
        )

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
        except ValidationError as e:
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
        except ValidationError as e:
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

    async def _fetch_suggested_geo_targets(self, storage_id: str):
        if not storage_id:
            return None

        storage_service = StorageService(
            access_token=auth_context.access_token,
            client_code=auth_context.client_code,
            x_forwarded_host=auth_context.x_forwarded_host,
            x_forwarded_port=auth_context.x_forwarded_port,
        )

        payload = StorageRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            dataObjectId=storage_id,
            clientCode=auth_context.client_code,
            eager=False,
            eagerFields=[],
        )

        response = await storage_service.read_storage(payload)

        if not response.success or not response.result:
            return None

        data = response.result

        try:
            if isinstance(data, list) and len(data) > 0:
                record = data[0]["result"]["result"]
            elif isinstance(data, dict):
                record = data["result"]["result"]
            else:
                return None
        except Exception:
            return None

        return record.get("suggestedGeoTargets")    

    async def _build_locations(
        self,
        suggested_geo_targets,
        allowed_countries,
    ) -> dict | None:

        if not suggested_geo_targets:
            return None

        async def resolve_target(target):
            results = await self.geo_targeting_adapter.search_locations(
                client_code=auth_context.client_code,
                location_name=target.get("canonicalName"),
                limit=3,
            )

            if not results:
                results = await self.geo_targeting_adapter.search_locations(
                client_code=auth_context.client_code,
                location_name=target.get("name"),
                limit=3,
            )

            if not results:
                return None

            if allowed_countries:
                matched = [
                    r for r in results
                    if r.get("country_code") in allowed_countries
                ]
                return matched[0] if matched else results[0]

            return results[0]

        tasks = [
            resolve_target(target)
            for target in suggested_geo_targets
            if target
        ]

        resolved_results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_locations = [
            r for r in resolved_results
            if r and not isinstance(r, Exception)
        ]

        if not valid_locations:
            return None

        return self.geo_targeting_adapter.build_geo_structure(valid_locations)


meta_adset_agent = MetaAdSetAgent()
