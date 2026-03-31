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

        logger.info(
            "meta_adset_geo.website_data_fetched",
            storage_id=getattr(website_data, "storage_id", None),
            suggested_geo_direct=getattr(website_data, "suggested_geo_targets", None),
        )

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

        logger.info(
            "meta_adset_detailed.llm_output",
            interests=detailed_targeting.interests,
            behaviors=detailed_targeting.behaviors,
            demographics=detailed_targeting.demographics,
        )

        audience_targeting = await self.targeting_adapter.build_flexible_spec(
            ad_account_id=ad_account_id,
            client_code=auth_context.client_code,
            interests=detailed_targeting.interests,
            behaviors=detailed_targeting.behaviors,
            demographics=detailed_targeting.demographics,
        )

        logger.info(
            "meta_adset_detailed.audience_targeting_result",
            audience_targeting_count=len(audience_targeting),
        )

        suggested_geo_targets = getattr(website_data, "suggested_geo_targets", None)

        if not suggested_geo_targets and getattr(website_data, "storage_id", None):
            suggested_geo_targets = await self._fetch_suggested_geo_targets(
                website_data.storage_id
            )

        logger.info(
            "meta_adset_geo.final_suggested_targets",
            suggested_geo_targets=suggested_geo_targets,
        )

        allowed_countries = getattr(website_data, "special_ad_category_country", None)
        if allowed_countries and isinstance(allowed_countries, str):
            allowed_countries = [allowed_countries]

        logger.info(
            "meta_adset_geo.enter_build_locations",
            suggested_geo_targets=suggested_geo_targets,
            allowed_countries=allowed_countries,
        )

        locations = await self._build_locations(
            suggested_geo_targets=suggested_geo_targets,
            allowed_countries=allowed_countries,
        )

        return {
            "genders": targeting.genders,
            "age_min": targeting.age_min,
            "age_max": targeting.age_max,
            "locales": locales,
            "audience_targeting": audience_targeting,
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
            raise AIProcessingException(
                "Detailed targeting LLM returned empty response"
            )

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

        if not response.success:
            return None

        # Standardized: Using response.content property for robust parsing
        if not response.content:
            return None

        record = response.content[0]
        return record.get("suggestedGeoTargets")

    async def _build_locations(
        self,
        suggested_geo_targets,
        allowed_countries,
    ) -> dict | None:

        logger.info(
            "meta_adset_geo.entering_build_locations",
            suggested_geo_targets=suggested_geo_targets,
            allowed_countries=allowed_countries,
        )

        if not suggested_geo_targets:
            logger.info("meta_adset_geo.no_suggested_targets")
            return None

        allowed_region = None
        if suggested_geo_targets:
            first = suggested_geo_targets[0]
            canonical = first.get("canonicalName")

            if canonical:
                parts = [p.strip() for p in canonical.split(",")]
                if len(parts) >= 2:
                    allowed_region = parts[-2].strip().lower()

        logger.info(
            "meta_adset_geo.derived_allowed_region",
            allowed_region=allowed_region,
        )

        all_valid_results = []

        async def resolve_target(target):
            logger.info("meta_adset_geo.resolving_target", target=target)

            canonical = target.get("canonicalName")

            results = await self.geo_targeting_adapter.search_locations(
                client_code=auth_context.client_code,
                location_name=canonical,
                limit=5,
            )

            if not results:
                results = await self.geo_targeting_adapter.search_locations(
                    client_code=auth_context.client_code,
                    location_name=target.get("name"),
                    limit=5,
                )

            if not results:
                return []

            filtered = []

            for r in results:
                if allowed_countries and r.get("country_code") not in allowed_countries:
                    continue

                if allowed_region and r.get("region"):
                    if r.get("region").strip().lower() != allowed_region:
                        continue

                filtered.append(r)

            return filtered

        tasks = [resolve_target(target) for target in suggested_geo_targets if target]

        resolved_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result_group in resolved_results:
            if isinstance(result_group, Exception) or not result_group:
                continue
            all_valid_results.extend(result_group)

        unique_by_key = {}
        for item in all_valid_results:
            key = item.get("key")
            if key:
                unique_by_key[key] = item

        final_locations = list(unique_by_key.values())

        logger.info(
            "meta_adset_geo.resolved_valid_locations",
            count=len(final_locations),
            locations=final_locations,
        )

        if not final_locations:
            logger.info("meta_adset_geo.no_valid_locations_after_resolve")
            return None

        return self.geo_targeting_adapter.build_geo_structure(final_locations)


meta_adset_agent = MetaAdSetAgent()
