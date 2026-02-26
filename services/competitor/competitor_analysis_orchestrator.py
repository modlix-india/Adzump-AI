import asyncio
from typing import Dict, Any, Optional, Tuple, List
from structlog import get_logger  # type: ignore
import structlog.contextvars

from oserver.services.storage_service import storage_service
from oserver.models.storage_request_model import (
    StorageReadRequest,
    StorageFilter,
    StorageUpdateWithPayload,
)
from services.business_service import BusinessService
from models.business_model import BusinessMetadata
from core.infrastructure.context import auth_context
from models.competitor_model import (
    Competitor,
    CompetitorKeyword,
    CompetitorAnalysisResult,
)
from exceptions.custom_exceptions import StorageException

# Local sub-module imports
from .competitor_discovery_service import competitor_discovery_service
from .competitor_insight_service import competitor_insight_service

logger = get_logger(__name__)


class CompetitorAnalysisOrchestrator:
    """Lean orchestrator for multi-page competitor keyword extraction."""

    STORAGE_NAME = "AISuggestedData"
    APP_CODE = "marketingai"

    def __init__(self):
        self.business_service = BusinessService()

    async def start_competitor_analysis(
        self,
        business_url: str,
        customer_id: Optional[str] = None,
        login_customer_id: Optional[str] = None,
    ) -> CompetitorAnalysisResult:
        """Main entry point to start the competitor analysis process."""
        structlog.contextvars.bind_contextvars(
            business_url=business_url, client_code=auth_context.client_code
        )
        logger.info("analysis.orchestration_started")

        try:
            # Load Initial Info
            record, storage_id, brand_info = await self._load_business_info(
                business_url
            )

            # Find Keywords (Now includes per-competitor enrichment)
            competitors = await self._find_competitor_keywords(
                record, brand_info, customer_id, login_customer_id
            )

            # Global Aggregation & Trend Analysis
            result = await self._add_metrics_and_save(
                competitors,
                record,
                brand_info,
                storage_id,
                customer_id,
                login_customer_id,
            )

            logger.info(
                "analysis.orchestration_complete", competitor_count=len(competitors)
            )
            return result
        finally:
            structlog.contextvars.unbind_contextvars("business_url", "client_code")

    async def _load_business_info(
        self, business_url: str
    ) -> Tuple[Dict[str, Any], str, BusinessMetadata]:
        """Fetch business record and resolve info context."""
        # 1. Fetch from storage
        read_req = StorageReadRequest(
            storageName=self.STORAGE_NAME,
            appCode=self.APP_CODE,
            clientCode=auth_context.client_code,
            filter=StorageFilter(field="businessUrl", value=business_url),
        )
        resp = await storage_service.read_page_storage(read_req)

        if not resp.success or not resp.result:
            raise StorageException(f"Failed to fetch record for {business_url}")

        content = resp.result[0].get("result", {}).get("result", {}).get("content", [])
        if not content:
            raise StorageException(f"Empty record for {business_url}")

        record = content[-1]
        storage_id = record.get("_id")
        if not storage_id:
            raise StorageException(f"Record for {business_url} missing ID")

        # 2. Resolve Brand Metadata & USPs in parallel
        summary = record.get("final_summary") or record.get("summary")
        if not summary:
            brand_info = BusinessMetadata.from_raw_data(record)
        else:
            logger.info("analysis.resolving_metadata")
            brand_info, usps = await asyncio.gather(
                self.business_service.extract_business_metadata(summary, business_url),
                self.business_service.extract_business_unique_features(summary),
                return_exceptions=True,
            )
            if isinstance(brand_info, Exception):
                brand_info = BusinessMetadata.from_raw_data(record)
            if not isinstance(usps, Exception):
                brand_info.unique_features = usps or brand_info.unique_features

        return record, storage_id, brand_info

    async def _find_competitor_keywords(
        self,
        record: Dict[str, Any],
        brand_info: BusinessMetadata,
        customer_id: Optional[str] = None,
        login_customer_id: Optional[str] = None,
    ) -> List[Competitor]:
        """Parallel keyword discovery across all listed competitors."""
        raw_competitors = record.get("competitors", [])
        if not raw_competitors:
            logger.warning("analysis.no_competitors_found")
            return []

        logger.info("analysis.discovery_started", count=len(raw_competitors))
        results = await asyncio.gather(
            *[
                competitor_discovery_service.find_keywords_for_competitor(
                    competitor_info=competitor,
                    record=record,
                    brand_info=brand_info,
                    customer_id=customer_id,
                    login_customer_id=login_customer_id,
                )
                for competitor in raw_competitors
            ],
            return_exceptions=True,
        )
        return [res for res in results if isinstance(res, Competitor)]

    def _build_global_dedup(
        self, competitors: List[Competitor]
    ) -> Dict[str, CompetitorKeyword]:
        """Deduplicate keywords across all competitors before enrichment."""
        deduped: Dict[str, CompetitorKeyword] = {}
        for comp in competitors:
            for kw in comp.extracted_keywords:
                key = kw.keyword.strip().lower()
                if key not in deduped or kw.relevance > deduped[key].relevance:
                    deduped[key] = kw

        total_before = sum(len(c.extracted_keywords) for c in competitors)
        logger.info(
            "analysis.dedup_complete",
            before=total_before,
            after=len(deduped),
        )
        return deduped

    def _propagate_metrics_to_competitors(
        self,
        competitors: List[Competitor],
        enriched_map: Dict[str, CompetitorKeyword],
    ) -> None:
        """Write enriched metrics back to each competitor's keyword list, preserving strategic context."""
        for comp in competitors:
            updated_keywords = []
            for kw in comp.extracted_keywords:
                key = kw.keyword.strip().lower()
                if key in enriched_map:
                    # ONLY propagate technical metrics, keep competitor-specific AI strategy
                    enriched = enriched_map[key]
                    updated_kw = kw.model_copy(
                        update={
                            "volume": enriched.volume,
                            "competition": enriched.competition,
                            "competitionIndex": enriched.competitionIndex,
                            "trend_direction": enriched.trend_direction,
                        }
                    )
                    updated_keywords.append(updated_kw)

            # Sort by opportunity score (competitor-specific)
            comp.extracted_keywords = sorted(
                updated_keywords,
                key=lambda x: x.opportunity_score,
                reverse=True,
            )

    async def _add_metrics_and_save(
        self,
        competitors: List[Competitor],
        record: Dict[str, Any],
        brand_info: BusinessMetadata,
        storage_id: str,
        customer_id: Optional[str],
        login_customer_id: Optional[str],
    ) -> CompetitorAnalysisResult:
        """Deduplicate globally, perform Trend Analysis on top keywords, and persist."""

        # Global Deduplication
        # Discovery keywords now already have Volume/Competition from Step 2.
        deduped_map = self._build_global_dedup(competitors)
        unique_list = list(deduped_map.values())

        enriched_keywords: List[CompetitorKeyword] = []

        if unique_list and customer_id and login_customer_id:
            try:
                # Final Trend Analysis & Global Scoring
                # Rationale: We only do Trends on the top unique candidates to save time.
                enriched_keywords = (
                    await competitor_insight_service.add_volume_and_trends(
                        keywords=unique_list,
                        customer_id=customer_id,
                        login_customer_id=login_customer_id,
                        skip_trends=False,  # Final pass includes Trends
                    )
                )

                brand_info.business_summary = (
                    record.get("final_summary") or record.get("summary") or ""
                )

                # Global strategic grading against the user's business
                enriched_keywords = (
                    await competitor_insight_service.rate_keyword_potential(
                        enriched_keywords, brand_info
                    )
                )

                # Ensure per-competitor lists stay in sync with final global list
                final_map = {kw.keyword.lower(): kw for kw in enriched_keywords}
                self._propagate_metrics_to_competitors(competitors, final_map)

            except Exception as e:
                logger.error("analysis.aggregation_failed", error=str(e))
                enriched_keywords = sorted(
                    unique_list, key=lambda x: x.relevance, reverse=True
                )
        else:
            enriched_keywords = sorted(
                unique_list, key=lambda x: x.relevance, reverse=True
            )

        result = CompetitorAnalysisResult(
            competitor_analysis=competitors, enriched_keywords=enriched_keywords
        )
        update_req = StorageUpdateWithPayload(
            storageName=self.STORAGE_NAME,
            dataObjectId=storage_id,
            clientCode=auth_context.client_code,
            dataObject=result.model_dump(),
            appCode=self.APP_CODE,
        )
        await storage_service.update_storage(update_req)
        return result


competitor_analysis_orchestrator = CompetitorAnalysisOrchestrator()
