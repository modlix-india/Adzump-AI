import asyncio
from typing import List, Optional, Dict, Any
from structlog import get_logger  # type: ignore

from config.scraper_config import ScraperConfig
from models.business_model import ScrapeResult, ScrapeError, BlockReason
from services.browser.scraper import Scraper
from services.browser.page_discovery import PageDiscovery
from services.browser.data_extractor import DataExtractor

logger = get_logger(__name__)


class BatchScraper:
    def __init__(
        self,
        scraper: Scraper,
        discovery: PageDiscovery,
        extractor: DataExtractor,
    ):
        self.scraper = scraper
        self.discovery = discovery
        self.extractor = extractor

    async def scrape_batch(
        self,
        urls: List[str],
        stop_on_error: bool = False,
    ) -> List[ScrapeResult]:
        logger.info(f"[BatchScraper] Scraping {len(urls)} URLs")

        tasks = [self.scraper.scrape(url) for url in urls]

        if stop_on_error:
            return await asyncio.gather(*tasks)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [
            r
            if isinstance(r, ScrapeResult)
            else ScrapeResult(
                success=False,
                url=urls[i],
                error=ScrapeError(type=BlockReason.CONNECTION_ERROR, message=str(r)),
            )
            for i, r in enumerate(results)
        ]

    async def scrape_with_discovery(
        self,
        url: str,
        max_pages: int = ScraperConfig.MAX_PAGES_TO_SCRAPE,
    ) -> ScrapeResult:
        logger.info(f"[BatchScraper] Discovery scrape: {url}")

        # 1. Scrape homepage
        homepage = await self.scraper.scrape(url)

        # 2. Handle empty homepage
        if not homepage.success or not self._has_content(homepage.data):
            fallback_urls = self.discovery._get_fallback_urls(url)
            fallback_results = await self.scrape_batch(fallback_urls)
            homepage = self._get_best_result(url, fallback_results)

        if not homepage.success:
            return homepage

        # 3. Discover & scrape valuable pages
        links = homepage.data.get("links", [])
        valuable_urls = await self.discovery.discover_pages(links, url)

        if valuable_urls:
            additional = await self.scrape_batch(valuable_urls[:max_pages])
            return self._merge_results(homepage, additional)

        return homepage

    def _has_content(self, data: Optional[Dict[str, Any]]) -> bool:
        return bool(data) and self.extractor.validate_content(data)

    def _get_best_result(self, url: str, results: List[ScrapeResult]) -> ScrapeResult:
        for r in results:
            if r.success and self._has_content(r.data):
                return r
        return (
            results[0]
            if results
            else ScrapeResult(
                success=False,
                url=url,
                error=ScrapeError(
                    type=BlockReason.EMPTY_CONTENT, message="No content found"
                ),
            )
        )

    def _merge_results(
        self, primary: ScrapeResult, additional: List[ScrapeResult]
    ) -> ScrapeResult:
        if not primary.data:
            return primary

        merged = primary.data.copy()
        warnings = primary.warnings.copy()

        for r in additional:
            if r.success and r.data:
                for key in [
                    "paragraphs",
                    "spans",
                    "divs",
                    "links",
                    "images",
                    "iframes",
                ]:
                    merged.setdefault(key, []).extend(r.data.get(key, []))
                for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                    h = merged.setdefault("headings", {})
                    h[tag] = h.get(tag, []) + r.data.get("headings", {}).get(tag, [])
                warnings.extend(r.warnings)

        return ScrapeResult(
            success=True, url=primary.url, warnings=warnings, data=merged
        )
