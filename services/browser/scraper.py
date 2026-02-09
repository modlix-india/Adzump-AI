from bs4 import BeautifulSoup
from structlog import get_logger  # type: ignore

from models.business_model import ScrapeResult, ScrapeError, BlockReason
from services.browser.page_fetcher import PageFetcher
from services.browser.content_detector import ContentDetector
from services.browser.data_extractor import DataExtractor

logger = get_logger(__name__)


class Scraper:
    def __init__(
        self,
        fetcher: PageFetcher,
        detector: ContentDetector,
        extractor: DataExtractor,
    ):
        self.fetcher = fetcher
        self.detector = detector
        self.extractor = extractor

    async def scrape(self, url: str) -> ScrapeResult:
        logger.info(f"[Scraper] Scraping: {url}")

        # Fetch page
        fetch_result = await self.fetcher.fetch(url)

        if not fetch_result.success:
            return ScrapeResult(
                success=False,
                url=url,
                warnings=fetch_result.warnings,
                error=fetch_result.error,
            )

        # Parse and extract
        soup = BeautifulSoup(fetch_result.html, "html.parser")

        # Check meta robots (warning only)
        if warning := self.detector.check_meta_robots(soup):
            fetch_result.warnings.append(warning)

        # Extract data
        data = self.extractor.extract(soup)

        # Validate content
        if not self.extractor.validate_content(data):
            return ScrapeResult(
                success=False,
                url=url,
                warnings=fetch_result.warnings,
                error=ScrapeError(
                    type=BlockReason.EMPTY_CONTENT,
                    message="No meaningful content extracted",
                ),
            )

        logger.info(f"[Scraper] Success: {url}")
        return ScrapeResult(
            success=True,
            url=url,
            warnings=fetch_result.warnings,
            data=data,
        )
