from __future__ import annotations
import json
import asyncio
from typing import Any
from structlog import get_logger, contextvars as sl_contextvars  # type: ignore
from contextvars import ContextVar

from services.scraper_service import scraper_service
from utils import helpers, competitor_extraction, google_autocomplete
from models.business_model import BusinessMetadata
from models.competitor_model import Competitor, CompetitorKeyword
from models.keyword_model import KeywordType, KeywordSuggestion
from exceptions.custom_exceptions import (
    ScraperException,
    BusinessValidationException,
)
from services.google_keywords_service import GoogleKeywordService
from services.business_service import BusinessService
from adapters.google.optimization.keyword_planner import keyword_planner_adapter

logger = get_logger(__name__)


class CompetitorDiscoveryService:
    """Service for per-competitor deep extraction and keyword discovery."""

    MAX_STRATEGIC_PAGES = 5
    MAX_AUTOCOMPLETE_SEEDS = 20
    MAX_STRATEGIC_SEEDS = 50
    AUTOCOMPLETE_RESULTS_PER_SEED = 10
    EXTRACTION_MODEL = "gpt-4o-mini"

    # Shared Task-Local Context (Scoped to individual competitor runs)
    competitor_context: ContextVar = ContextVar("competitor_context")

    def __init__(self):
        self.keyword_service = GoogleKeywordService()
        self.business_service = BusinessService()
        self.planner = keyword_planner_adapter

    async def find_keywords_for_competitor(
        self,
        competitor_info: Competitor,
        customer_id: str,
        login_customer_id: str,
    ) -> Competitor:
        """Deep keyword discovery for a single competitor using the robust business pipeline."""
        url = competitor_info.url
        name = competitor_info.name
        sl_contextvars.bind_contextvars(competitor_name=name, competitor_url=url)

        # Initialize Task-Local Context
        context_token = self.competitor_context.set(
            {
                "url": url,
                "customer_id": customer_id,
                "login_customer_id": login_customer_id,
            }
        )

        try:
            # Competitor Intelligence Gathering (Scraping + Summarization + Identity)
            (
                comp_summary,
                competitor_brand_info,
                competitor_features,
                pages_scraped,
            ) = await self._extract_competitor_intelligence(url)

            # Update Context with intelligence results
            ctx = self.competitor_context.get()
            ctx.update(
                {
                    "comp_summary": comp_summary,
                    "competitor_brand_info": competitor_brand_info,
                    "competitor_features": competitor_features,
                }
            )
            self.competitor_context.set(ctx)

            # Competitor Strategic Seed Identification
            (
                brand_seeds,
                generic_seeds,
            ) = await self._generate_competitor_strategic_seeds()

            # Competitor Dual-Branch (Parallel expansion & filtering)
            brand_branch_task = self._discover_competitor_branch_keywords(
                seeds=brand_seeds,
                kw_type=KeywordType.BRAND,
            )
            generic_branch_task = self._discover_competitor_branch_keywords(
                seeds=generic_seeds,
                kw_type=KeywordType.GENERIC,
            )

            brand_results, generic_results = await asyncio.gather(
                brand_branch_task, generic_branch_task
            )
            final_keywords = brand_results + generic_results

            logger.info(
                "Competitor analysis.discovery_complete",
                brand_count=len(brand_results),
                generic_count=len(generic_results),
                final_count=len(final_keywords),
            )

            return Competitor(
                name=name,
                url=url,
                pages_scraped=pages_scraped,
                is_validated=True,
                extracted_keywords=final_keywords,
                summary=comp_summary,
                reasoning=competitor_info.reasoning,
                features=competitor_features,
            )
        finally:
            self.competitor_context.reset(context_token)
            sl_contextvars.unbind_contextvars("competitor_name", "competitor_url")

    async def _extract_competitor_intelligence(
        self, url: str
    ) -> tuple[str, BusinessMetadata, list[str], int]:
        """Scrape the competitor site and build a strategic profile (Summary + Metadata + Features)."""
        # Competitor Website Scraping
        home_data, all_links = await self._scrape_homepage(url)
        strategic_urls = await competitor_extraction.select_strategic_pages(
            links=all_links,
            base_url=url,
            model=self.EXTRACTION_MODEL,
            max_pages=self.MAX_STRATEGIC_PAGES,
        )
        # Competitor Sub-Pages Scraping
        sub_pages = await self._scrape_strategic_pages(strategic_urls)

        all_page_data = [home_data] + sub_pages
        merged_content = competitor_extraction.merge_page_data(all_page_data)
        pages_scraped = len(all_page_data)

        # Competitor Website Summarization
        summary_raw = await self.business_service.generate_website_summary(
            scraped_data=merged_content
        )
        comp_summary = json.loads(summary_raw).get("summary", "")

        # Competitor Identity Extraction (Parallel)
        metadata_task = self.business_service.extract_business_metadata(
            scraped_data=comp_summary, url=url
        )
        features_task = self.business_service.extract_business_unique_features(
            scraped_data=comp_summary
        )

        competitor_brand_info, competitor_features = await asyncio.gather(
            metadata_task, features_task
        )

        logger.info(
            "Competitor analysis.intelligence_gathered",
            pages=pages_scraped,
            brand_name=competitor_brand_info.brand_name,
            feature_count=len(competitor_features),
        )

        return comp_summary, competitor_brand_info, competitor_features, pages_scraped

    async def _generate_competitor_strategic_seeds(self) -> tuple[list[str], list[str]]:
        """Identify initial Brand and Generic seed keywords using the context."""
        ctx = self.competitor_context.get()

        brand_task = self.keyword_service.generate_seed_keywords(
            scraped_data=ctx["comp_summary"],
            url=ctx["url"],
            brand_info=ctx["competitor_brand_info"],
            unique_features=ctx["competitor_features"],
            max_kw=self.MAX_STRATEGIC_SEEDS,
            keyword_type=KeywordType.BRAND,
        )
        generic_task = self.keyword_service.generate_seed_keywords(
            scraped_data=ctx["comp_summary"],
            url=ctx["url"],
            brand_info=ctx["competitor_brand_info"],
            unique_features=ctx["competitor_features"],
            max_kw=self.MAX_STRATEGIC_SEEDS,
            keyword_type=KeywordType.GENERIC,
        )

        return await asyncio.gather(brand_task, generic_task)

    async def _discover_competitor_branch_keywords(
        self,
        seeds: list[str],
        kw_type: KeywordType,
    ) -> list[CompetitorKeyword]:
        """Perform expansion and strategic selection using the task-local context."""
        if not seeds:
            return []

        ctx = self.competitor_context.get()

        # Competitor Seed Expansion (Autocomplete)
        expanded = await google_autocomplete.batch_fetch_autocomplete_suggestions(
            seeds[: self.MAX_AUTOCOMPLETE_SEEDS],
            max_results_per_seed=self.AUTOCOMPLETE_RESULTS_PER_SEED,
        )
        full_seed_set = list(set(seeds + expanded))

        # Competitor Keyword Ideas Enrichment (Keyword Planner)
        customer_id = ctx["customer_id"]
        login_customer_id = ctx["login_customer_id"]

        planner_results = await self.planner.generate_keyword_ideas(
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            seed_keywords=full_seed_set,
            url=ctx["url"],
        )

        # Competitor Keywords Strategic Selection
        suggestions = [KeywordSuggestion(**p) for p in planner_results]

        # Filter for volume > 0 as bidding on zero-volume terms is inefficient
        filtered_suggestions = [s for s in suggestions if s.volume > 0]

        optimized = await self.keyword_service.select_positive_keywords(
            all_suggestions=filtered_suggestions,
            business_info=ctx["competitor_brand_info"],
            unique_features=ctx["competitor_features"],
            scraped_data=ctx["comp_summary"],
            keyword_type=kw_type,
            url=ctx["url"],
        )

        # Unified Mapping
        final_keywords = [
            CompetitorKeyword(
                keyword=opt.keyword,
                volume=opt.volume,
                competition=opt.competition,
                competitionIndex=opt.competitionIndex,
                match_type=opt.match_type.value.upper(),
                reasoning=opt.rationale,
                source="google_ads",
                category=kw_type.value.title(),
            )
            for opt in optimized
        ]

        logger.info(
            "Competitor discovery.branch_complete",
            type=kw_type.value,
            seeds=len(seeds),
            expanded=len(full_seed_set),
            selected=len(final_keywords),
        )
        return final_keywords

    async def _scrape_homepage(self, url: str) -> tuple[dict[str, Any], list[dict]]:
        """Validate domain and scrape homepage. Returns page data and links."""
        is_valid, error = await helpers.validate_domain_exists(url)
        if not is_valid:
            logger.warning("competitor.invalid_domain", error=error)
            raise BusinessValidationException(f"Invalid domain: {error}")

        result = await scraper_service.scrape(url=url)
        if not result.success:
            err = result.error.message if result.error else "unknown"
            logger.warning("competitor.scrape_failed", error=err)
            raise ScraperException(f"Scrape failed: {err}")

        return result.data, result.data.get("links", [])

    async def _scrape_strategic_pages(self, urls: list[str]) -> list[dict[str, Any]]:
        """Scrape strategic sub-pages, returning only successful results."""
        if not urls:
            return []

        results = await asyncio.gather(
            *[scraper_service.scrape(url=u) for u in urls], return_exceptions=True
        )
        return [r.data for r in results if not isinstance(r, Exception) and r.success]


competitor_discovery_service = CompetitorDiscoveryService()
