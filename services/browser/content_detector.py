from typing import Optional
from bs4 import BeautifulSoup
from playwright.async_api import Response
from structlog import get_logger  # type: ignore

from config.scraper_config import ScraperConfig
from models.business_model import ScrapeError, ScrapeWarning, BlockReason, WarningType

logger = get_logger(__name__)


class ContentDetector:
    def detect_block(self, response: Response, html: str) -> Optional[ScrapeError]:
        # Layer 1: HTTP Status (instant, no parsing)
        if error := self._check_http_status(response):
            logger.warning("[ContentDetector] Block detected at Layer 1 (HTTP Status)")
            return error

        # Layer 2: Response Headers (detect WAF before parsing)
        if error := self._check_headers(response):
            logger.warning("[ContentDetector] Block detected at Layer 2 (Headers)")
            return error

        # Layer 3: DOM-based detection (accurate, structured)
        soup = BeautifulSoup(html, "html.parser")
        if error := self._check_dom(soup):
            logger.warning("[ContentDetector] Block detected at Layer 3 (DOM)")
            return error

        # Layer 4: Pattern fallback (catch edge cases)
        if error := self._check_patterns(html):
            logger.warning("[ContentDetector] Block detected at Layer 4 (Pattern)")
            return error

        return None

    def _check_http_status(self, response: Response) -> Optional[ScrapeError]:
        if response.status in ScraperConfig.STATUS_BLOCK_MAP:
            return ScrapeError(
                type=ScraperConfig.STATUS_BLOCK_MAP[response.status],
                message=f"HTTP {response.status}: Access denied by server",
            )
        return None

    def _check_headers(self, response: Response) -> Optional[ScrapeError]:
        headers = response.headers

        # Cloudflare challenge (mitigated = challenge issued)
        if "cf-ray" in headers and "cf-mitigated" in headers:
            return ScrapeError(
                type=BlockReason.BOT_PROTECTION, message="Cloudflare challenge detected"
            )

        # Sucuri WAF
        if "x-sucuri-id" in headers:
            return ScrapeError(
                type=BlockReason.BOT_PROTECTION, message="Sucuri WAF detected"
            )

        # Akamai
        if "x-akamai-transformed" in headers:
            # This alone isn't a block, but combined with other signals...
            pass

        return None

    def _check_dom(self, soup: BeautifulSoup) -> Optional[ScrapeError]:
        # Cloudflare challenge page
        if soup.find(id="cf-wrapper") or soup.find(class_="cf-browser-verification"):
            return ScrapeError(
                type=BlockReason.BOT_PROTECTION,
                message="Cloudflare verification page detected",
            )

        # Cloudflare turnstile
        if soup.find(class_="cf-turnstile"):
            return ScrapeError(
                type=BlockReason.CAPTCHA_REQUIRED,
                message="Cloudflare Turnstile detected",
            )

        # reCAPTCHA
        if soup.find(class_="g-recaptcha") or soup.find(id="recaptcha"):
            return ScrapeError(
                type=BlockReason.CAPTCHA_REQUIRED, message="reCAPTCHA detected"
            )

        # hCaptcha
        if soup.find(class_="h-captcha"):
            return ScrapeError(
                type=BlockReason.CAPTCHA_REQUIRED, message="hCaptcha detected"
            )

        return None

    def _check_patterns(self, html: str) -> Optional[ScrapeError]:
        html_lower = html.lower()

        # Check CAPTCHA patterns
        for pattern in ScraperConfig.CAPTCHA_PATTERNS:
            if pattern.lower() in html_lower:
                return ScrapeError(
                    type=BlockReason.CAPTCHA_REQUIRED,
                    message=f"CAPTCHA pattern detected: {pattern}",
                )

        # Check bot protection patterns
        for pattern, provider in ScraperConfig.BOT_PROTECTION_PATTERNS:
            if pattern.lower() in html_lower:
                return ScrapeError(
                    type=BlockReason.BOT_PROTECTION,
                    message=f"{provider} protection detected",
                )

        return None

    def check_meta_robots(self, soup: BeautifulSoup) -> Optional[ScrapeWarning]:
        meta_robots = soup.find("meta", attrs={"name": "robots"})

        if meta_robots:
            content = meta_robots.get("content", "").lower()

            if "noindex" in content:
                return ScrapeWarning(
                    type=WarningType.META_NOINDEX, message="Page has 'noindex' meta tag"
                )

            if "nofollow" in content:
                return ScrapeWarning(
                    type=WarningType.META_NOFOLLOW,
                    message="Page has 'nofollow' meta tag",
                )

        return None
