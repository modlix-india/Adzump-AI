from typing import Optional, List, Tuple
from structlog import get_logger  # type: ignore

from models.business_model import ScrapeResult, ScrapeError, ScreenshotResponse
from services.browser.browser_pool import BrowserPool
from services.browser.concurrency_limiter import ConcurrencyLimiter
from services.browser.page_fetcher import PageFetcher
from services.browser.content_detector import ContentDetector
from services.browser.data_extractor import DataExtractor
from services.browser.page_discovery import PageDiscovery
from services.browser.screenshot_storage_handler import ScreenshotStorageHandler
from services.browser.scraper import Scraper
from services.browser.screenshot_handler import ScreenshotHandler
from services.browser.batch_scraper import BatchScraper

logger = get_logger(__name__)


class WebPageService:
    def __init__(
        self,
        access_token: Optional[str] = None,
        client_code: Optional[str] = None,
        x_forwarded_host: Optional[str] = None,
        x_forwarded_port: Optional[str] = None,
    ):
        self.pool = BrowserPool()
        self.limiter = ConcurrencyLimiter()
        self.detector = ContentDetector()
        self.extractor = DataExtractor()

        fetcher = PageFetcher(self.pool, self.limiter)
        self._scraper = Scraper(fetcher, self.detector, self.extractor)
        self._discovery = PageDiscovery()
        self._batch = BatchScraper(self._scraper, self._discovery, self.extractor)

        storage = None
        if access_token and client_code:
            storage = ScreenshotStorageHandler(
                access_token, client_code, x_forwarded_host, x_forwarded_port
            )
        self._screenshot = ScreenshotHandler(
            self.pool, self.limiter, self.detector, storage
        )

        logger.info("[WebPageService] Initialized")

    async def scrape(self, url: str) -> ScrapeResult:
        return await self._scraper.scrape(url)

    async def scrape_batch(
        self, urls: List[str], stop_on_error: bool = False
    ) -> List[ScrapeResult]:
        return await self._batch.scrape_batch(urls, stop_on_error)

    async def scrape_with_discovery(self, url: str, max_pages: int = 5) -> ScrapeResult:
        return await self._batch.scrape_with_discovery(url, max_pages)

    async def screenshot(
        self, url: str, full_page: bool = True
    ) -> Tuple[Optional[bytes], Optional[ScrapeError]]:
        return await self._screenshot.capture(url, full_page)

    async def screenshot_with_storage(
        self, business_url: str, url: str, retake: bool = False
    ) -> ScreenshotResponse:
        return await self._screenshot.capture_with_storage(business_url, url, retake)

    async def close(self) -> None:
        await self.pool.close()
