import json
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from structlog import get_logger  # type: ignore
import structlog.contextvars

from services.scraper_service import scraper_service
from services import openai_client
from utils import prompt_loader
from utils.helpers import validate_domain_exists
from utils.competitor_extraction import (
    merge_page_data,
    select_strategic_pages,
)
from utils.google_autocomplete import batch_fetch_autocomplete_suggestions
from models.business_model import BusinessMetadata
from models.competitor_model import (
    Competitor,
    CompetitorKeyword,
)
from exceptions.custom_exceptions import (
    ScraperException,
    BusinessValidationException,
)
from .competitor_insight_service import competitor_insight_service

logger = get_logger(__name__)


class CompetitorDiscoveryService:
    """Service for per-competitor deep extraction and keyword discovery."""

    MAX_STRATEGIC_PAGES = 5
    AUTOCOMPLETE_RELEVANCE = 0.6
    MAX_AI_KEYWORDS = 30
    MAX_AUTOCOMPLETE_SEEDS = 5
    MAX_STRATEGIC_SEEDS = 10
    AUTOCOMPLETE_RESULTS_PER_SEED = 5
    SINGLE_ANALYSIS_TIMEOUT = 90

    # Model Selection: We use GPT-4o for deep strategy and mini for fast extraction
    STRATEGY_MODEL = "gpt-4o"
    EXTRACTION_MODEL = "gpt-4o-mini"

    # Max words per autocomplete seed — Google works best on short queries.
    SEED_MAX_WORDS = 5
    # Min characters after cleaning — avoids sending single-word or empty seeds.
    SEED_MIN_CHARS = 8

    async def find_keywords_for_competitor(
        self,
        competitor_info: Dict[str, str],
        record: Dict[str, Any],
        brand_info: BusinessMetadata,
        customer_id: Optional[str] = None,
        login_customer_id: Optional[str] = None,
    ) -> Competitor:
        """Deep keyword discovery for a single competitor."""
        url = competitor_info.get("url")
        name = competitor_info.get("name")
        structlog.contextvars.bind_contextvars(competitor_name=name, competitor_url=url)

        try:
            # Content Gathering (Validation + AI Link Selection)
            # Rationale: Replaces legacy heuristic-based path matching with industry-agnostic AI.
            home_data, all_links = await self._scrape_homepage(url)

            # AI-Guided Discovery: Pick the most valuable internal pages
            strategic_urls = await select_strategic_pages(
                links=all_links,
                base_url=url,
                model=self.EXTRACTION_MODEL,
                max_pages=self.MAX_STRATEGIC_PAGES,
            )
            sub_pages = await self._scrape_strategic_pages(strategic_urls)

            all_page_data = [home_data] + sub_pages
            structured_scraped_data = merge_page_data(all_page_data)
            pages_scraped = len(all_page_data)

            # AI Seed Generation & Context Distillation
            # Rationale: We distill the competitor's positioning and USPs here
            # to anchor all subsequent keyword decisions in strategic intent.
            ai_seeds, comp_summary = await self.generate_strategic_seeds(
                competitor_name=name,
                scraped_data=structured_scraped_data,
                max_kw=self.MAX_STRATEGIC_SEEDS,
            )
            logger.info(
                "competitor.context_distilled",
                summary=comp_summary,
                seed_count=len(ai_seeds),
            )

            # Autocomplete Expansion
            # We take the AI seeds and expand them via Google Autocomplete.
            raw_autocomplete = await batch_fetch_autocomplete_suggestions(
                ai_seeds[: self.MAX_AUTOCOMPLETE_SEEDS],
                max_results_per_seed=self.AUTOCOMPLETE_RESULTS_PER_SEED,
            )

            # URL-Aware Enrichment (Keyword Planner)
            candidate_seeds = list(set(ai_seeds + raw_autocomplete))
            enriched_keywords = []

            if customer_id and login_customer_id:
                # Convert strings to CompetitorKeyword objects for the insight service
                candidate_kws = [
                    CompetitorKeyword(keyword=kw, source="discovery")
                    for kw in candidate_seeds
                ]

                # Enrichment with the Competitor's URL - capturing exactly what they bid on
                enriched_keywords = (
                    await competitor_insight_service.add_volume_and_trends(
                        keywords=candidate_kws,
                        customer_id=customer_id,
                        login_customer_id=login_customer_id,
                        url=url,  # Targets the competitor domain directly
                        skip_trends=True,  # Global trends happen in the orchestrator
                    )
                )

            # Strategic Filtering (LLM) - Now Context-Aware
            # Prune and score keywords using both OUR USPs and THE COMPETITOR'S positioning
            final_keywords = await self._strategic_filter_pass(
                name=name,
                competitor_summary=comp_summary,
                enriched_keywords=enriched_keywords
                or [
                    CompetitorKeyword(keyword=kw, source="discovery")
                    for kw in candidate_seeds
                ],
                brand_info=brand_info,
            )

            logger.info(
                "competitor.discovery_complete",
                final_count=len(final_keywords),
                enriched=bool(customer_id),
            )

            return Competitor(
                name=name,
                url=url,
                pages_scraped=pages_scraped,
                is_validated=True,
                extracted_keywords=final_keywords,
                summary=comp_summary,  # Persist context for the UI/Reports
                reasoning=competitor_info.get("reasoning"),  # Why they are a competitor
                features=competitor_info.get("features", []),  # Core detected features
            )
        finally:
            structlog.contextvars.unbind_contextvars(
                "competitor_name", "competitor_url"
            )

    async def _scrape_homepage(self, url: str) -> Tuple[Dict[str, Any], List[Dict]]:
        """Validate domain and scrape homepage. Returns page data and links."""
        is_valid, error = await validate_domain_exists(url)
        if not is_valid:
            logger.warning("competitor.invalid_domain", error=error)
            raise BusinessValidationException(f"Invalid domain: {error}")

        result = await scraper_service.scrape(url)
        if not result.success:
            err = result.error.message if result.error else "unknown"
            logger.warning("competitor.scrape_failed", error=err)
            raise ScraperException(f"Scrape failed: {err}")

        return result.data, result.data.get("links", [])

    async def _scrape_strategic_pages(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Scrape strategic sub-pages, returning only successful results."""
        if not urls:
            return []

        results = await asyncio.gather(
            *[scraper_service.scrape(u) for u in urls], return_exceptions=True
        )
        return [r.data for r in results if not isinstance(r, Exception) and r.success]

    async def generate_strategic_seeds(
        self,
        competitor_name: str,
        scraped_data: List[Dict[str, Any]],
        max_kw: int = 10,
    ) -> Tuple[List[str], str]:
        """Use AI to distill context and generate strategic search seeds."""
        prompt = prompt_loader.format_prompt(
            "competitor/strategic_seeds_prompt.txt",
            competitor_name=competitor_name,
            scraped_data=json.dumps(scraped_data),
            max_kw=max_kw,
        )

        try:
            resp = await openai_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.STRATEGY_MODEL,
                response_format={"type": "json_object"},
            )
            raw = json.loads(resp.choices[0].message.content.strip())
            seeds = raw.get("seeds") or raw.get("keywords") or []
            summary = raw.get("summary", "")
            return [str(s).strip() for s in seeds if s][:max_kw], str(summary).strip()
        except Exception as e:
            logger.warning("competitor.seed_generation_failed", error=str(e))
            return [], ""

    async def _strategic_filter_pass(
        self,
        name: str,
        competitor_summary: str,
        enriched_keywords: List[CompetitorKeyword],
        brand_info: BusinessMetadata,
    ) -> List[CompetitorKeyword]:
        """Final AI pass to prune and score keywords using deep competitor context."""
        if not enriched_keywords:
            return []

        prompt = prompt_loader.format_prompt(
            "competitor/strategic_filter_prompt.txt",
            competitor_name=name,
            competitor_summary=competitor_summary,
            brand_name=brand_info.brand_name,
            business_type=brand_info.business_type,
            unique_features=", ".join(brand_info.unique_features),
            keywords_json=json.dumps([kw.model_dump() for kw in enriched_keywords]),
        )

        try:
            resp = await openai_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.STRATEGY_MODEL,
                response_format={"type": "json_object"},
            )
            raw = json.loads(resp.choices[0].message.content.strip())
            results = raw.get("recommendations", [])

            # Map results back to objects using Pydantic update patterns
            id_map = {kw.keyword.lower(): kw for kw in enriched_keywords}
            final = []
            for r in results:
                kw_text = r.get("keyword", "").lower()
                base = id_map.get(kw_text)
                if not base or r.get("opportunity_score", 0) <= 0:
                    continue

                updates = {
                    k: v
                    for k, v in r.items()
                    if k in type(base).model_fields and v is not None
                }

                # Special case: normalize category
                if "category" in updates:
                    updates["category"] = (
                        str(updates["category"]).strip().title() or "General"
                    )

                # Create a fresh updated instance and append
                final.append(base.model_copy(update=updates))
            return final
        except Exception as e:
            logger.warning("competitor.strategic_filter_failed", error=str(e))
            return enriched_keywords[: self.MAX_AI_KEYWORDS]


competitor_discovery_service = CompetitorDiscoveryService()
