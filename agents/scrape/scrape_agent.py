"""Observable website scrape pipeline.

Breaks BusinessService.process_website_data() into discrete, observable steps.
Each step emits progress via on_progress callback so callers can track what's happening.
"""

import asyncio
import json
from typing import Callable, Optional

from structlog import get_logger

from exceptions.custom_exceptions import ScraperException
from models.business_model import (
    LocationInfo,
    ScrapeResult,
    WebsiteSummaryResponse,
)
from oserver.models.storage_request_model import (
    StorageFilter,
    StorageReadRequest,
    StorageRequestWithPayload,
    StorageUpdateWithPayload,
)
from oserver.services.storage_service import StorageService
from services.geo_target_service import GeoTargetService
from services.openai_client import chat_completion
from services.scraper_service import ScraperService
from utils.helpers import normalize_url
from utils.prompt_loader import format_prompt

logger = get_logger(__name__)

OPENAI_MODEL = "gpt-4o-mini"

ProgressCallback = Callable[[str, str, str], None]


class ScrapeAgent:
    """Observable website scrape pipeline with per-step progress.

    Each step calls on_progress(step, phase, message) so callers can
    surface real-time progress to users.
    """

    async def run(
        self,
        url: str,
        access_token: str,
        client_code: str,
        x_forwarded_host: str,
        x_forwarded_port: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> WebsiteSummaryResponse:
        """Execute full scrape pipeline with per-step progress."""
        emit = on_progress or _noop

        url = normalize_url(url)
        storage = StorageService(
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port,
        )

        # Step 1: Check storage cache
        emit("check_storage", "start", f"Searching cached analysis of {url}")
        existing_id, existing_record = await self._check_storage(url, client_code, storage)
        if existing_id and existing_record:
            emit("check_storage", "end", "Found cached analysis")
            business_type = existing_record.get("businessType", "")
            location = existing_record.get("location", {})
            area = location.get("area_location", "") if isinstance(location, dict) else ""
            emit("ai_analysis", "start", "Loading cached AI analysis")
            emit("ai_analysis", "end", f"Business type: {business_type}" if business_type else "Analysis loaded")
            if area or (isinstance(location, dict) and location.get("product_coordinates")):
                emit("geo_targeting", "start", "Loading cached geo targets")
                cached_targets = existing_record.get("suggestedGeoTargets", [])
                emit("geo_targeting", "end", f"{len(cached_targets)} location(s) loaded" if cached_targets else "No geo targets cached")
            return self._build_cached_response(url, existing_id, existing_record)
        emit("check_storage", "end", "No cached data found")

        # Step 2: Fetch website
        emit("fetch_website", "start", f"Fetching {url} via browser")
        scraped_data = await self._scrape_website(url)
        word_count = sum(len(p.split()) for p in scraped_data.get("paragraphs", []))
        link_count = len(scraped_data.get("links", []))
        map_count = len(scraped_data.get("map_embeds", []))
        emit("fetch_website", "end", f"Extracted {word_count:,} words, {link_count} links, {map_count} map embeds")

        # Step 3: AI analysis
        emit("ai_analysis", "start", "Analyzing content with AI")
        summary_text, business_type, location_info = await self._generate_summary(scraped_data)
        emit("ai_analysis", "end", f"Business type: {business_type}" if business_type else "Analysis complete")

        # Step 4: Geo targeting (optional — skip if no location signals, graceful on failure)
        has_coordinates = bool(scraped_data.get("map_embeds", []))
        area = location_info.area_location if location_info else None
        geo_targets: list[dict] = []
        unresolved: list[str] = []

        if not has_coordinates and not area:
            emit("geo_targeting", "start", "Skipping geo targeting")
            emit("geo_targeting", "end", "No location data found on website")
        else:
            emit("geo_targeting", "start", f"Resolving locations from {area or 'map coordinates'}")
            try:
                geo_targets, unresolved, location_info = await asyncio.wait_for(
                    self._suggest_geo_targets(scraped_data, location_info, client_code),
                    timeout=45,
                )
                target_names = [t["name"] for t in geo_targets[:4]]
                geo_summary = ", ".join(target_names)
                if len(geo_targets) > 4:
                    geo_summary += f" +{len(geo_targets) - 4} more"
                emit("geo_targeting", "end", f"Mapped: {geo_summary}" if target_names else "No locations resolved")
            except asyncio.TimeoutError:
                logger.warning("geo_targeting_timeout", url=url)
                emit("geo_targeting", "end", "Timed out — skipping")
            except Exception as e:
                logger.warning("geo_targeting_failed", url=url, error=str(e))
                emit("geo_targeting", "end", f"Skipped: {e}")

        # Step 5: Save results
        emit("save_results", "start", "Writing analysis to storage")
        storage_id = await self._write_storage(
            url, summary_text, business_type, location_info,
            geo_targets, scraped_data, existing_id, storage,
        )
        emit("save_results", "end", "Saved")

        return WebsiteSummaryResponse(
            storage_id=storage_id or existing_id,
            business_url=url,
            business_type=business_type,
            summary=summary_text,
            final_summary=summary_text,
            location=location_info,
            suggested_geo_targets=geo_targets,
            unresolved_locations=unresolved,
        )

    async def _check_storage(
        self, url: str, client_code: str, storage: StorageService
    ) -> tuple[Optional[str], Optional[dict]]:
        """Check if URL already exists in storage. Returns (id, record) or (None, None)."""
        read_request = StorageReadRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            clientCode=client_code,
            filter=StorageFilter(field="businessUrl", value=url),
            size=1,
        )
        response = await storage.read_page_storage(read_request)

        if not response.success or not response.result:
            return None, None

        try:
            records = (
                response.result[0]
                .get("result", {})
                .get("result", {})
                .get("content", [])
            )
            if records:
                record = records[-1]
                record_id = record.get("_id")
                summary = record.get("summary", "")
                if record_id and summary and summary.strip():
                    return record_id, record
        except Exception as e:
            logger.warning("storage_parse_error", error=str(e))

        return None, None

    def _build_cached_response(
        self, url: str, storage_id: str, record: dict
    ) -> WebsiteSummaryResponse:
        location_data = record.get("location", {})
        location_info = (
            LocationInfo(
                area_location=location_data.get("area_location"),
                product_location=location_data.get("product_location"),
                product_coordinates=location_data.get("product_coordinates"),
            )
            if location_data
            else None
        )
        return WebsiteSummaryResponse(
            storage_id=storage_id,
            business_url=url,
            business_type=record.get("businessType", ""),
            summary=record.get("summary", ""),
            final_summary=record.get("finalSummary", ""),
            location=location_info,
        )

    async def _scrape_website(self, url: str) -> dict:
        """Scrape website HTML and extract structured data."""
        scraper = ScraperService()
        result: ScrapeResult = await scraper.scrape(url)

        if not result.success:
            error_msg = result.error.message if result.error else "Failed to scrape website"
            raise ScraperException(
                message=error_msg,
                details={
                    "block_reason": result.error.type.value if result.error else "unknown",
                    "url": url,
                    "warnings": [
                        {"type": w.type.value, "message": w.message}
                        for w in result.warnings
                    ],
                },
            )

        if result.warnings:
            for w in result.warnings:
                logger.warning("scrape_warning", url=url, message=w.message)

        return result.data or {}

    async def _generate_summary(
        self, scraped_data: dict
    ) -> tuple[str, str, Optional[LocationInfo]]:
        """Generate website summary via LLM. Returns (summary, business_type, location_info)."""
        prompt = format_prompt(
            "business/website_summary_prompt.txt", scraped_data=scraped_data
        )
        response = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model=OPENAI_MODEL,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = json.loads(raw.replace("'", '"'))

        summary_text = parsed.get("summary", "")
        business_type = parsed.get("businessType", "")
        location_data = parsed.get("location", {})
        location_info = (
            LocationInfo(area_location=location_data.get("area_location", ""))
            if location_data
            else None
        )

        return summary_text, business_type, location_info

    async def _suggest_geo_targets(
        self,
        scraped_data: dict,
        location_info: Optional[LocationInfo],
        client_code: str,
    ) -> tuple[list[dict], list[str], Optional[LocationInfo]]:
        """Suggest geo targets from scraped data. Returns (targets, unresolved, updated_location)."""
        geo_service = GeoTargetService(client_code=client_code)

        coordinates = None
        map_embeds = scraped_data.get("map_embeds", [])
        if map_embeds and map_embeds[0].get("coordinates"):
            coordinates = map_embeds[0]["coordinates"]

        geo_result = await geo_service.suggest_geo_targets(
            coordinates=coordinates,
            area_location=location_info.area_location if location_info else None,
            radius_km=15,
        )

        if location_info:
            location_info.product_location = geo_result.product_location
            location_info.product_coordinates = geo_result.product_coordinates

        targets = [
            {
                "name": loc.name,
                "resourceName": loc.resource_name,
                "canonicalName": loc.canonical_name,
                "targetType": loc.target_type,
            }
            for loc in geo_result.locations
        ]

        return targets, geo_result.unresolved, location_info

    async def _write_storage(
        self,
        url: str,
        summary: str,
        business_type: str,
        location_info: Optional[LocationInfo],
        geo_targets: list[dict],
        scraped_data: dict,
        existing_id: Optional[str],
        storage: StorageService,
    ) -> Optional[str]:
        """Write or update storage record. Returns storage_id."""
        location_dict = {
            "area_location": location_info.area_location if location_info else None,
            "product_location": location_info.product_location if location_info else None,
            "product_coordinates": location_info.product_coordinates if location_info else None,
        }

        data_object = {
            "businessUrl": url,
            "summary": summary,
            "businessType": business_type,
            "finalSummary": summary,
            "siteLinks": scraped_data.get("links", []),
            "mapEmbeds": scraped_data.get("map_embeds", []),
            "location": location_dict,
            "suggestedGeoTargets": geo_targets,
        }

        if existing_id:
            update_payload = StorageUpdateWithPayload(
                storageName="AISuggestedData",
                appCode="marketingai",
                dataObjectId=existing_id,
                dataObject={k: v for k, v in data_object.items() if k != "businessUrl"},
            )
            await storage.update_storage(update_payload)
            return existing_id

        create_payload = StorageRequestWithPayload(
            storageName="AISuggestedData",
            appCode="marketingai",
            dataObject=data_object,
        )
        create_response = await storage.write_storage(create_payload)
        return _extract_storage_id(create_response.result)


def _extract_storage_id(result_block) -> Optional[str]:
    """Extract _id from storage create response."""
    if isinstance(result_block, dict):
        return result_block.get("dataObjectId") or (
            result_block.get("result", {}).get("result", {}).get("_id")
        )
    if isinstance(result_block, list) and result_block:
        item = result_block[0]
        if "dataObjectId" in item:
            return item["dataObjectId"]
        if isinstance(item, dict) and "result" in item:
            return item.get("result", {}).get("result", {}).get("_id")
    return None


def _noop(step: str, phase: str, message: str) -> None:
    pass
