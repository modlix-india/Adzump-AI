from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from structlog import get_logger  # type: ignore
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from typing import Optional, List, Tuple, Dict
import httpx
import re

from models.business_model import (
    ScrapeResult,
    ScrapeWarning,
    ScrapeError,
    WarningType,
    BlockReason,
)

logger = get_logger(__name__)


class ScraperService:
    """Web scraper with detection and extraction capabilities."""

    # Detection patterns for CAPTCHA
    CAPTCHA_PATTERNS = [
        "g-recaptcha",
        "h-captcha",
        "cf-turnstile",
        'id="captcha"',
        'class="captcha"',
        "recaptcha",
        "hcaptcha",
    ]

    # Detection patterns for bot protection
    BOT_PROTECTION_PATTERNS = [
        ("Checking your browser", "cloudflare"),
        ("Just a moment...", "cloudflare"),
        ("cf-browser-verification", "cloudflare"),
        ("Attention Required!", "cloudflare"),
        ("Please Wait... | Cloudflare", "cloudflare"),
        ("Access Denied", "waf"),
        ("Bot detected", "generic"),
        ("Please enable JavaScript", "js_required"),
        ("Enable JavaScript and cookies", "js_required"),
    ]

    # HTTP status to block reason mapping
    STATUS_BLOCK_MAP = {
        403: BlockReason.HTTP_FORBIDDEN,
        429: BlockReason.RATE_LIMITED,
        503: BlockReason.SERVICE_UNAVAILABLE,
    }

    async def scrape(self, url: str) -> ScrapeResult:
        """
        Main entry point - scrape a website with permission detection.

        Returns:
            ScrapeResult with success status, warnings, errors, and extracted data.
        """
        logger.info(f"[Scraper] Starting scrape for: {url}")
        warnings: List[ScrapeWarning] = []

        # STEP 1: Check robots.txt (WARNING only - still proceed)
        robots_warning = await self._check_robots_txt(url)
        if robots_warning:
            warnings.append(robots_warning)

        # STEP 2: Fetch HTML with Playwright
        html, error_result = await self._fetch_html(url, warnings)
        if error_result:
            return error_result

        # STEP 3: Check for CAPTCHA (BLOCK)
        captcha_error = self._detect_captcha(html)
        if captcha_error:
            return ScrapeResult(
                success=False, url=url, warnings=warnings, error=captcha_error
            )

        # STEP 4: Check for bot protection (BLOCK)
        bot_error = self._detect_bot_protection(html)
        if bot_error:
            return ScrapeResult(
                success=False, url=url, warnings=warnings, error=bot_error
            )

        # STEP 5: Parse content
        soup = BeautifulSoup(html, "html.parser")

        # STEP 6: Check meta robots (WARNING only)
        meta_warning = self._check_meta_robots(soup)
        if meta_warning:
            warnings.append(meta_warning)

        # STEP 7: Extract data
        data = self._extract_page_data(soup)

        # STEP 8: Validate content (BLOCK if empty)
        if not self._validate_content(data):
            logger.warning(f"[Scraper] No meaningful content extracted from {url}")
            return ScrapeResult(
                success=False,
                url=url,
                warnings=warnings,
                error=ScrapeError(
                    type=BlockReason.EMPTY_CONTENT,
                    message="No meaningful content extracted. The site may be blocking bots or the page is empty.",
                ),
            )

        # SUCCESS
        self._log_success(url, data, warnings)
        return ScrapeResult(success=True, url=url, warnings=warnings, data=data)

    async def _check_robots_txt(self, url: str) -> Optional[ScrapeWarning]:
        """Check robots.txt for the given URL. Returns warning if disallowed."""
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(robots_url)

                if response.status_code == 404:
                    logger.info(f"[Scraper] No robots.txt found for {parsed.netloc}")
                    return None

                if response.status_code != 200:
                    logger.warning(
                        f"[Scraper] Could not fetch robots.txt: HTTP {response.status_code}"
                    )
                    return None

                rp = RobotFileParser()
                rp.parse(response.text.splitlines())

                if not rp.can_fetch("*", url):
                    logger.warning(f"[Scraper] robots.txt disallows scraping: {url}")
                    return ScrapeWarning(
                        type=WarningType.ROBOTS_TXT,
                        message="This website's robots.txt discourages automated scraping. Proceeding anyway.",
                    )

                return None

        except Exception as e:
            logger.warning(f"[Scraper] Error checking robots.txt: {e}")
            return None

    def _detect_captcha(self, html: str) -> Optional[ScrapeError]:
        """Detect CAPTCHA elements in the HTML."""
        html_lower = html.lower()

        for pattern in self.CAPTCHA_PATTERNS:
            if pattern.lower() in html_lower:
                logger.warning(f"[Scraper] CAPTCHA detected: {pattern}")
                return ScrapeError(
                    type=BlockReason.CAPTCHA_REQUIRED,
                    message="This website requires CAPTCHA verification. Unable to scrape.",
                )

        return None

    def _detect_bot_protection(self, html: str) -> Optional[ScrapeError]:
        """Detect bot protection/challenge pages."""
        for pattern, provider in self.BOT_PROTECTION_PATTERNS:
            if pattern.lower() in html.lower():
                logger.warning(
                    f"[Scraper] Bot protection detected: {provider} - {pattern}"
                )
                return ScrapeError(
                    type=BlockReason.BOT_PROTECTION,
                    message=f"This website uses {provider} bot protection. Unable to scrape.",
                )

        return None

    def _check_meta_robots(self, soup: BeautifulSoup) -> Optional[ScrapeWarning]:
        """Check for meta robots tags that discourage indexing."""
        meta_robots = soup.find("meta", attrs={"name": "robots"})

        if meta_robots:
            content = meta_robots.get("content", "").lower()

            if "noindex" in content:
                logger.info("[Scraper] Meta robots noindex detected")
                return ScrapeWarning(
                    type=WarningType.META_NOINDEX,
                    message="This page has 'noindex' meta tag. Content may not be intended for public access.",
                )

            if "nofollow" in content:
                logger.info("[Scraper] Meta robots nofollow detected")
                return ScrapeWarning(
                    type=WarningType.META_NOFOLLOW,
                    message="This page has 'nofollow' meta tag.",
                )

        return None

    def _extract_page_data(self, soup: BeautifulSoup) -> dict:
        """Extract structured data from the parsed HTML."""
        return {
            "title": soup.title.string.strip()
            if soup.title and soup.title.string
            else "",
            "meta": {
                "description": (
                    soup.find("meta", attrs={"name": "description"})
                    .get("content", "")
                    .strip()
                    if soup.find("meta", attrs={"name": "description"})
                    else ""
                ),
                "keywords": (
                    soup.find("meta", attrs={"name": "keywords"})
                    .get("content", "")
                    .strip()
                    if soup.find("meta", attrs={"name": "keywords"})
                    else ""
                ),
            },
            "headings": {
                tag: [h.get_text(strip=True) for h in soup.find_all(tag)]
                for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]
            },
            "paragraphs": [
                p.get_text(strip=True)
                for p in soup.find_all("p")
                if p.get_text(strip=True)
            ],
            "spans": [
                span.get_text(strip=True)
                for span in soup.find_all("span")
                if span.get_text(strip=True)
            ],
            "divs": [
                div.get_text(strip=True)
                for div in soup.find_all("div")
                if div.get_text(strip=True)
            ],
            "lists": {
                "unordered": [
                    [li.get_text(strip=True) for li in ul.find_all("li")]
                    for ul in soup.find_all("ul")
                ],
                "ordered": [
                    [li.get_text(strip=True) for li in ol.find_all("li")]
                    for ol in soup.find_all("ol")
                ],
            },
            "tables": [
                {
                    "headers": [th.get_text(strip=True) for th in table.find_all("th")],
                    "rows": [
                        [td.get_text(strip=True) for td in row.find_all("td")]
                        for row in table.find_all("tr")
                        if row.find_all("td")
                    ],
                }
                for table in soup.find_all("table")
            ],
            "links": [
                {"text": a.get_text(strip=True), "href": a["href"]}
                for a in soup.find_all("a", href=True)
            ],
            "images": [
                {"alt": img.get("alt", ""), "src": img["src"]}
                for img in soup.find_all("img", src=True)
            ],
            "iframes": [
                {"src": iframe.get("src", ""), "title": iframe.get("title", "")}
                for iframe in soup.find_all("iframe", src=True)
            ],
            "map_embeds": [
                {
                    "src": iframe.get("src", ""),
                    "title": iframe.get("title", ""),
                    "coordinates": self._extract_coordinates(iframe.get("src", "")),
                }
                for iframe in soup.find_all("iframe", src=True)
                if iframe.get("src")
                and (
                    "google.com/maps" in iframe.get("src", "")
                    or "maps.google.com" in iframe.get("src", "")
                )
            ],
        }

    def _extract_coordinates(self, url: str) -> Optional[Dict[str, float]]:
        """
        Extract lat/lng coordinates from Google Maps embed URL.
        Pattern: !2d<longitude>!3d<latitude>
        """
        if not url:
            return None
        match = re.search(r"!2d([-\d.]+)!3d([-\d.]+)", url)
        if match:
            try:
                return {"lng": float(match.group(1)), "lat": float(match.group(2))}
            except ValueError:
                return None
        return None

    def _validate_content(self, data: dict) -> bool:
        """Validate that meaningful content was extracted."""
        has_title = bool(data.get("title"))
        has_headings = any(
            len(headings) > 0 for headings in data.get("headings", {}).values()
        )
        has_paragraphs = len(data.get("paragraphs", [])) > 0
        return has_title or has_headings or has_paragraphs

    # ========== PRIVATE: Helper Methods ==========

    def _get_block_reason_for_status(self, status_code: int) -> BlockReason:
        """Map HTTP status codes to block reasons."""
        return self.STATUS_BLOCK_MAP.get(status_code, BlockReason.HTTP_FORBIDDEN)

    async def _fetch_html(
        self, url: str, warnings: List[ScrapeWarning]
    ) -> Tuple[Optional[str], Optional[ScrapeResult]]:
        """
        Fetch HTML content using Playwright.

        Returns:
            Tuple of (html_content, error_result)
            - If successful: (html, None)
            - If failed: (None, ScrapeResult with error)
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                await page.set_extra_http_headers(
                    {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                )

                response = await page.goto(url, wait_until="load", timeout=60000)

                # Check HTTP status (BLOCK on 403/429/503)
                if response and response.status in [403, 429, 503]:
                    await browser.close()
                    logger.warning(f"[Scraper] HTTP {response.status} - Access denied")
                    return None, ScrapeResult(
                        success=False,
                        url=url,
                        warnings=warnings,
                        error=ScrapeError(
                            type=self._get_block_reason_for_status(response.status),
                            message=f"HTTP {response.status}: Access denied by the server.",
                        ),
                    )

                await page.wait_for_timeout(5000)
                html = await page.content()
                await browser.close()
                return html, None

        except Exception as e:
            error_str = str(e)
            logger.error(f"[Scraper] Playwright error: {e}")

            error_result = self._handle_fetch_error(url, warnings, error_str)
            return None, error_result

    def _handle_fetch_error(
        self, url: str, warnings: List[ScrapeWarning], error_str: str
    ) -> ScrapeResult:
        """Handle fetch errors and return appropriate ScrapeResult."""
        if "ERR_HTTP2_PROTOCOL_ERROR" in error_str:
            return ScrapeResult(
                success=False,
                url=url,
                warnings=warnings,
                error=ScrapeError(
                    type=BlockReason.BOT_PROTECTION,
                    message="This website has bot protection that is blocking access. Unable to scrape.",
                ),
            )
        elif (
            "ERR_CONNECTION_REFUSED" in error_str
            or "ERR_NAME_NOT_RESOLVED" in error_str
        ):
            return ScrapeResult(
                success=False,
                url=url,
                warnings=warnings,
                error=ScrapeError(
                    type=BlockReason.CONNECTION_ERROR,
                    message="Could not connect to the website. Please check if the URL is correct.",
                ),
            )
        elif "Timeout" in error_str:
            return ScrapeResult(
                success=False,
                url=url,
                warnings=warnings,
                error=ScrapeError(
                    type=BlockReason.TIMEOUT,
                    message="The website took too long to respond. Please try again later.",
                ),
            )
        else:
            return ScrapeResult(
                success=False,
                url=url,
                warnings=warnings,
                error=ScrapeError(
                    type=BlockReason.CONNECTION_ERROR,
                    message=f"Failed to connect to the website: {error_str[:200]}",
                ),
            )

    def _log_success(self, url: str, data: dict, warnings: List[ScrapeWarning]) -> None:
        """Log successful scrape details."""
        logger.info(f"[Scraper] ========== SCRAPE SUCCESS: {url} ==========")
        logger.info(f"[Scraper] Title: {data['title']}")
        logger.info(
            f"[Scraper] Meta Description: {data['meta'].get('description', '')[:200]}"
        )
        logger.info(
            f"[Scraper] Meta Keywords: {data['meta'].get('keywords', '')[:200]}"
        )
        logger.info(f"[Scraper] Headings: {data['headings']}")
        logger.info(
            f"[Scraper] Paragraphs ({len(data['paragraphs'])}): {data['paragraphs'][:5]}{'...' if len(data['paragraphs']) > 5 else ''}"
        )
        logger.info(
            f"[Scraper] Spans ({len(data['spans'])}): {data['spans'][:5]}{'...' if len(data['spans']) > 5 else ''}"
        )
        logger.info(
            f"[Scraper] Divs ({len(data['divs'])}): {len(data['divs'])} items extracted"
        )
        logger.info(
            f"[Scraper] Lists - Unordered: {len(data['lists']['unordered'])}, Ordered: {len(data['lists']['ordered'])}"
        )
        logger.info(f"[Scraper] Tables: {len(data['tables'])} tables extracted")
        logger.info(
            f"[Scraper] Links ({len(data['links'])}): {data['links'][:5]}{'...' if len(data['links']) > 5 else ''}"
        )
        logger.info(
            f"[Scraper] Images ({len(data['images'])}): {data['images'][:5]}{'...' if len(data['images']) > 5 else ''}"
        )
        logger.info(f"[Scraper] Iframes: {len(data['iframes'])} iframes extracted")
        map_embeds = data.get("map_embeds", [])
        logger.info(f"[Scraper] Map Embeds: {len(map_embeds)} Google Maps embeds found")
        for i, embed in enumerate(map_embeds):
            coords = embed.get("coordinates")
            if coords:
                logger.info(
                    f"[Scraper]   Map {i + 1}: lat={coords.get('lat')}, lng={coords.get('lng')}"
                )
            else:
                logger.info(f"[Scraper]   Map {i + 1}: No coordinates extracted")
        if warnings:
            logger.info(
                f"[Scraper] Warnings ({len(warnings)}): {[w.type.value for w in warnings]}"
            )
        logger.info("[Scraper] ========== END SCRAPE ==========")


# Singleton instance
scraper_service = ScraperService()
