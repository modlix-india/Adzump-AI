from typing import Optional, Tuple
import base64
from structlog import get_logger  # type: ignore

from config.scraper_config import ScraperConfig
from models.business_model import ScrapeError, BlockReason, ScreenshotResponse
from services.browser.browser_pool import BrowserPool
from services.browser.concurrency_limiter import ConcurrencyLimiter
from services.browser.content_detector import ContentDetector
from services.browser.screenshot_storage_handler import ScreenshotStorageHandler

logger = get_logger(__name__)


class ScreenshotHandler:
    def __init__(
        self,
        pool: BrowserPool,
        limiter: ConcurrencyLimiter,
        detector: ContentDetector,
        storage: Optional[ScreenshotStorageHandler] = None,
    ):
        self.pool = pool
        self.limiter = limiter
        self.detector = detector
        self.storage = storage

    async def capture(
        self,
        url: str,
        full_page: bool = True,
    ) -> Tuple[Optional[bytes], Optional[ScrapeError]]:
        logger.info(f"[ScreenshotHandler] Capturing: {url}")

        async with self.limiter.acquire():
            async with self.pool.page() as page:
                try:
                    response = await page.goto(
                        url,
                        wait_until="load",
                        timeout=ScraperConfig.PAGE_TIMEOUT_MS,
                    )

                    if not response:
                        return None, ScrapeError(
                            type=BlockReason.CONNECTION_ERROR,
                            message="No response from server",
                        )

                    # Check for blocks
                    html = await page.content()
                    if error := self.detector.detect_block(response, html):
                        return None, error

                    # Wait and capture
                    await page.wait_for_timeout(ScraperConfig.SCREENSHOT_WAIT_MS)
                    return await page.screenshot(full_page=full_page), None

                except Exception as e:
                    return None, ScrapeError(
                        type=BlockReason.CONNECTION_ERROR,
                        message=f"Screenshot failed: {str(e)[:200]}",
                    )

    async def capture_with_storage(
        self,
        business_url: str,
        url: str,
        retake: bool = False,
    ) -> ScreenshotResponse:
        if not self.storage:
            raise RuntimeError("Storage not initialized")

        # Check cache
        if not retake:
            cached = await self.storage.get_cached_screenshot(business_url, url)
            if cached:
                _, storage_id = await self.storage.get_record(business_url)
                return ScreenshotResponse(
                    url=url, storage_id=storage_id, screenshot=cached
                )

        # Capture new
        screenshot_bytes, error = await self.capture(url)
        if error:
            raise RuntimeError(f"Screenshot failed: {error.message}")

        # Try upload - fallback to base64 if storage fails
        try:
            screenshot_url = await self.storage.upload_screenshot(screenshot_bytes, url)
            storage_id = await self.storage.save_screenshot(
                business_url, url, screenshot_url
            )
            return ScreenshotResponse(
                url=url, storage_id=storage_id, screenshot=screenshot_url
            )
        except Exception as e:
            logger.warning(
                f"[ScreenshotHandler] Storage upload failed, returning base64: {e}"
            )
            b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            return ScreenshotResponse(
                url=url, storage_id=None, screenshot=f"data:image/png;base64,{b64}"
            )
