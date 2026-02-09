from dataclasses import dataclass, field
from typing import Optional, List
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx
from playwright.async_api import Page, Response
from structlog import get_logger  # type: ignore

from config.scraper_config import ScraperConfig
from models.business_model import (
    ScrapeError,
    ScrapeWarning,
    BlockReason,
    WarningType,
)
from services.browser.browser_pool import BrowserPool
from services.browser.concurrency_limiter import ConcurrencyLimiter
from services.browser.content_detector import ContentDetector
from services.browser.data_extractor import DataExtractor

logger = get_logger(__name__)


@dataclass
class PageFetchResult:
    success: bool
    html: Optional[str] = None
    response: Optional[Response] = None
    error: Optional[ScrapeError] = None
    warnings: List[ScrapeWarning] = field(default_factory=list)


class PageFetcher:
    def __init__(
        self,
        browser_pool: BrowserPool,
        concurrency_limiter: ConcurrencyLimiter,
    ):
        self.pool = browser_pool
        self.limiter = concurrency_limiter
        self.detector = ContentDetector()
        self.extractor = DataExtractor()

    async def fetch(
        self,
        url: str,
        check_robots: bool = True,
    ) -> PageFetchResult:
        warnings: List[ScrapeWarning] = []

        # Check robots.txt (warning only, don't block)
        if check_robots:
            if warning := await self._check_robots_txt(url):
                warnings.append(warning)

        # Fetch with concurrency limiting and browser pooling
        async with self.limiter.acquire():
            async with self.pool.page() as page:
                try:
                    result = await self._do_fetch(page, url, warnings)
                    return result
                except Exception as e:
                    error = self._handle_error(str(e))
                    return PageFetchResult(
                        success=False,
                        error=error,
                        warnings=warnings,
                    )

    async def _do_fetch(
        self,
        page: Page,
        url: str,
        warnings: List[ScrapeWarning],
    ) -> PageFetchResult:
        response = await page.goto(
            url,
            wait_until="load",
            timeout=ScraperConfig.PAGE_TIMEOUT_MS,
        )

        if not response:
            return PageFetchResult(
                success=False,
                error=ScrapeError(
                    type=BlockReason.CONNECTION_ERROR,
                    message="No response received from server",
                ),
                warnings=warnings,
            )

        # Wait for dynamic content
        await page.wait_for_timeout(ScraperConfig.PAGE_WAIT_MS)

        # Get HTML
        html = await page.content()

        # Run detection
        if block_error := self.detector.detect_block(response, html):
            return PageFetchResult(
                success=False,
                error=block_error,
                warnings=warnings,
            )

        return PageFetchResult(
            success=True,
            html=html,
            response=response,
            warnings=warnings,
        )

    async def _check_robots_txt(self, url: str) -> Optional[ScrapeWarning]:
        """Check robots.txt (warning only)."""
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(robots_url)

                if response.status_code == 404:
                    return None

                if response.status_code != 200:
                    return None

                rp = RobotFileParser()
                rp.parse(response.text.splitlines())

                if not rp.can_fetch("*", url):
                    return ScrapeWarning(
                        type=WarningType.ROBOTS_TXT,
                        message="robots.txt discourages scraping this page",
                    )

                return None

        except Exception as e:
            logger.warning(f"[PageFetcher] robots.txt check failed: {e}")
            return None

    def _handle_error(self, error_str: str) -> ScrapeError:
        """Convert exception to appropriate ScrapeError."""
        if "ERR_HTTP2_PROTOCOL_ERROR" in error_str:
            return ScrapeError(
                type=BlockReason.BOT_PROTECTION,
                message="Bot protection blocking access",
            )
        elif (
            "ERR_CONNECTION_REFUSED" in error_str
            or "ERR_NAME_NOT_RESOLVED" in error_str
        ):
            return ScrapeError(
                type=BlockReason.CONNECTION_ERROR,
                message="Could not connect to website",
            )
        elif "Timeout" in error_str:
            return ScrapeError(
                type=BlockReason.TIMEOUT, message="Website took too long to respond"
            )
        else:
            return ScrapeError(
                type=BlockReason.CONNECTION_ERROR,
                message=f"Failed to fetch page: {error_str[:200]}",
            )
