from __future__ import annotations
import asyncio
from typing import Any
from structlog import get_logger  # type: ignore
import structlog.contextvars as sl_contextvars

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
from utils.competitor_extraction import filter_already_analyzed_competitors

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
        customer_id: str,
        login_customer_id: str,
        force_fresh_analysis: bool = False,
    ) -> CompetitorAnalysisResult:
        """Main entry point to start the competitor analysis process."""
        sl_contextvars.bind_contextvars(
            business_url=business_url, client_code=auth_context.client_code
        )
        logger.info("Competitor analysis.orchestration_started")

        try:
            # Load Initial User Context
            (
                record,
                storage_id,
                user_business_info,
            ) = await self._load_user_business_context(business_url=business_url)

            # Instantiate strict Pydantic models at the database(storage) boundary (standardized)
            raw_comps, existing_comps = CompetitorAnalysisResult.load_from_record(
                record
            )

            # Find Keywords (Now includes per-competitor enrichment)
            competitors = await self._find_competitor_keywords(
                raw_competitors=raw_comps,
                existing_analysis=existing_comps,
                customer_id=customer_id,
                login_customer_id=login_customer_id,
                force_fresh_analysis=force_fresh_analysis,
            )

            # Global Aggregation & Trend Analysis
            result = await self._enrich_competitor_keyword_with_trends_and_save(
                competitors=competitors,
                user_business_info=user_business_info,
                storage_id=storage_id,
            )

            logger.info(
                "Competitor analysis.orchestration_complete", competitor_count=len(competitors)
            )
            return result
        finally:
            sl_contextvars.unbind_contextvars("business_url", "client_code")

    async def _load_user_business_context(
        self, business_url: str
    ) -> tuple[dict[str, Any], str, BusinessMetadata]:
        """Fetch business record and resolve info context."""
        # 1. Fetch from storage
        read_req = StorageReadRequest(
            storageName=self.STORAGE_NAME,
            appCode=self.APP_CODE,
            clientCode=auth_context.client_code,
            filter=StorageFilter(field="businessUrl", value=business_url),
        )
        resp = await storage_service.read_page_storage(request=read_req)

        if not resp.success or not resp.result:
            raise StorageException(f"Failed to fetch record for {business_url}")

        # Standardized: Using response.content property for robust parsing (ReadPage)
        content = resp.content
        if not content:
            raise StorageException(f"Empty record for {business_url}")

        record = content[-1]
        storage_id = record.get("_id")
        if not storage_id:
            raise StorageException(f"Record for {business_url} missing ID")

        # 2. Resolve User Brand Metadata & USPs in parallel
        summary = record.get("final_summary") or record.get("summary")
        if not summary:
            user_business_info = BusinessMetadata.from_raw_data(record)
        else:
            user_business_info, usps = await asyncio.gather(
                self.business_service.extract_business_metadata(
                    scraped_data=summary, url=business_url
                ),
                self.business_service.extract_business_unique_features(
                    scraped_data=summary
                ),
                return_exceptions=True,
            )
            if isinstance(user_business_info, Exception):
                user_business_info = BusinessMetadata.from_raw_data(record)
            if not isinstance(usps, Exception):
                user_business_info.unique_features = (
                    usps or user_business_info.unique_features
                )
            user_business_info.business_summary = summary

        return record, storage_id, user_business_info

    async def _find_competitor_keywords(
        self,
        raw_competitors: list[Competitor],
        existing_analysis: list[Competitor],
        customer_id: str,
        login_customer_id: str,
        force_fresh_analysis: bool = False,
    ) -> list[Competitor]:
        """Parallel keyword discovery across all listed competitors with smart skipping."""
        if not raw_competitors:
            logger.warning("Competitor analysis.no_competitors_found")
            return []

        # Identify "already-done" competitors vs "to-discover"
        to_discover, already_done_list = filter_already_analyzed_competitors(
            raw_competitors=raw_competitors,
            existing_analysis=existing_analysis,
            force_fresh_analysis=force_fresh_analysis,
        )

        if not to_discover:
            logger.info(
                "Competitor analysis.discovery_skipped",
                total=len(raw_competitors),
                msg="All competitors already analyzed",
            )
            return already_done_list

        logger.info(
            "Competitor analysis.discovery_started",
            to_discover_count=len(to_discover),
            skipped_count=len(already_done_list),
            force_fresh=force_fresh_analysis,
        )

        # Discover only what's needed
        results = await asyncio.gather(
            *[
                competitor_discovery_service.find_keywords_for_competitor(
                    competitor_info=competitor,
                    customer_id=customer_id,
                    login_customer_id=login_customer_id,
                )
                for competitor in to_discover
            ],
            return_exceptions=True,
        )

        # Merge results
        valid_results = already_done_list
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                url = to_discover[i].url
                logger.error(
                    "Competitor analysis.discovery_failed",
                    url=url,
                    error=str(res),
                )
            else:
                valid_results.append(res)

        return valid_results

    def _build_global_dedup(
        self, competitors: list[Competitor]
    ) -> dict[str, CompetitorKeyword]:
        """Deduplicate keywords across all competitors before enrichment."""
        deduped: dict[str, CompetitorKeyword] = {}
        for comp in competitors:
            for kw in comp.extracted_keywords:
                key = kw.keyword.strip().lower()
                if key not in deduped or kw.volume > deduped[key].volume:
                    deduped[key] = kw

        total_before = sum(len(c.extracted_keywords) for c in competitors)
        logger.info(
            "Competitor analysis.dedup_complete",
            before=total_before,
            after=len(deduped),
        )
        return deduped

    def _propagate_metrics_to_competitors(
        self,
        competitors: list[Competitor],
        enriched_map: dict[str, CompetitorKeyword],
    ) -> None:
        """Write enriched metrics back to each competitor's keyword list, preserving strategic context."""
        for comp in competitors:
            updated_keywords = []
            for kw in comp.extracted_keywords:
                key = kw.keyword.strip().lower()
                if key in enriched_map:
                    # Propagate technical AND global AI grading metrics
                    enriched = enriched_map[key]
                    updated_kw = kw.model_copy(
                        update={
                            "volume": enriched.volume,
                            "competition": enriched.competition,
                            "competitionIndex": enriched.competitionIndex,
                            "trend_direction": enriched.trend_direction,
                            "opportunity_score": enriched.opportunity_score,
                            "recommended_action": enriched.recommended_action,
                            "reasoning": enriched.reasoning,
                            "competitor_advantage": enriched.competitor_advantage,
                        }
                    )
                    updated_keywords.append(updated_kw)

            # Sort by opportunity score (competitor-specific)
            comp.extracted_keywords = sorted(
                updated_keywords,
                key=lambda x: x.opportunity_score,
                reverse=True,
            )

    async def _enrich_competitor_keyword_with_trends_and_save(
        self,
        competitors: list[Competitor],
        user_business_info: BusinessMetadata,
        storage_id: str,
    ) -> CompetitorAnalysisResult:
        """Deduplicate globally, perform Trend Analysis on top keywords, and persist."""

        # Global Deduplication
        # Discovery keywords now already have Volume/Competition from competitor_discovery_service.
        deduped_map = self._build_global_dedup(competitors)
        unique_list = list(deduped_map.values())

        enriched_keywords: list[CompetitorKeyword] = unique_list

        if unique_list:
            try:
                # Final Trend Analysis & Global Scoring
                enriched_keywords = (
                    await competitor_insight_service.enrich_competitor_keyword_trends(
                        keywords=unique_list,
                    )
                )

                # Global strategic grading against the target user's business
                enriched_keywords = (
                    await competitor_insight_service.rate_keyword_potential(
                        enriched_keywords=enriched_keywords,
                        business_metadata=user_business_info,
                        competitor_names=[c.name for c in competitors],
                    )
                )

                # Ensure per-competitor lists stay in sync with final global list
                # Finally, sort by Opportunity Score (Descending) and then Volume for UI presentation
                enriched_keywords.sort(key=lambda x: (x.opportunity_score, x.volume), reverse=True)

                final_map = {kw.keyword.lower(): kw for kw in enriched_keywords}
                self._propagate_metrics_to_competitors(competitors, final_map)

            except Exception as e:
                logger.error("Competitor analysis.aggregation_failed", error=str(e))
                # Fallback: maintain volume sorting even on partial failure
                enriched_keywords = sorted(
                    unique_list, key=lambda x: x.volume, reverse=True
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
        await storage_service.update_storage(request=update_req)
        return result


competitor_analysis_orchestrator = CompetitorAnalysisOrchestrator()
