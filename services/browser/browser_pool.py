import asyncio
from contextlib import asynccontextmanager
from typing import Optional, List, AsyncGenerator
from playwright.async_api import async_playwright, Browser, Page, Playwright
from structlog import get_logger  # type: ignore

from config.scraper_config import ScraperConfig

logger = get_logger(__name__)


class BrowserPool:
    def __init__(
        self,
        max_browsers: int = ScraperConfig.MAX_CONCURRENT_BROWSERS,
        max_pages_per_browser: int = ScraperConfig.MAX_PAGES_PER_BROWSER,
    ):
        self.max_browsers = max_browsers
        self.max_pages_per_browser = max_pages_per_browser

        self._playwright: Optional[Playwright] = None
        self._browsers: List[Browser] = []
        self._page_counts: List[int] = []
        self._lock = asyncio.Lock()
        self._initialized = False

        logger.info(
            "[BrowserPool] Configured",
            max_browsers=max_browsers,
            max_pages_per_browser=max_pages_per_browser,
        )

    async def _initialize(self) -> None:
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            logger.info("[BrowserPool] Initializing browser pool...")
            self._playwright = await async_playwright().start()

            for i in range(self.max_browsers):
                browser = await self._playwright.chromium.launch(headless=True)
                self._browsers.append(browser)
                self._page_counts.append(0)
                logger.info(
                    f"[BrowserPool] Launched browser {i + 1}/{self.max_browsers}"
                )

            self._initialized = True
            logger.info("[BrowserPool] Pool ready")

    async def _get_available_browser(self) -> tuple[Browser, int]:
        await self._initialize()

        while True:
            async with self._lock:
                # Find browser with lowest page count under limit
                for idx, count in enumerate(self._page_counts):
                    if count < self.max_pages_per_browser:
                        self._page_counts[idx] += 1
                        return self._browsers[idx], idx

            # All browsers at capacity, wait and retry
            await asyncio.sleep(0.1)

    async def _release_browser(self, browser_idx: int) -> None:
        """Release a page slot from browser."""
        async with self._lock:
            if 0 <= browser_idx < len(self._page_counts):
                self._page_counts[browser_idx] = max(
                    0, self._page_counts[browser_idx] - 1
                )

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page, None]:
        browser, browser_idx = await self._get_available_browser()
        page = await browser.new_page()

        # Configure page
        await page.set_extra_http_headers({"User-Agent": ScraperConfig.USER_AGENT})

        try:
            yield page
        finally:
            await page.close()
            await self._release_browser(browser_idx)

    async def close(self) -> None:
        logger.info("[BrowserPool] Closing pool...")

        for browser in self._browsers:
            await browser.close()

        if self._playwright:
            await self._playwright.stop()

        self._browsers = []
        self._page_counts = []
        self._initialized = False
        logger.info("[BrowserPool] Pool closed")

    @property
    def stats(self) -> dict:
        return {
            "browsers": len(self._browsers),
            "page_counts": self._page_counts.copy(),
            "total_active_pages": sum(self._page_counts),
            "max_capacity": self.max_browsers * self.max_pages_per_browser,
        }
