from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from structlog import get_logger  # type: ignore
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from typing import Optional
import httpx

from models.scrape_permission_model import (
    ScrapeResult,
    ScrapeWarning,
    ScrapeError,
    WarningType,
    BlockReason,
)

logger = get_logger(__name__)

# Detection patterns
CAPTCHA_PATTERNS = [
    "g-recaptcha",
    "h-captcha",
    "cf-turnstile",
    'id="captcha"',
    'class="captcha"',
    "recaptcha",
    "hcaptcha",
]

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


async def check_robots_txt(url: str) -> Optional[ScrapeWarning]:
    """
    Check robots.txt for the given URL.
    Returns a warning if scraping is disallowed (but we still proceed).
    """
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(robots_url)
            
            if response.status_code == 404:
                # No robots.txt = allowed
                logger.info(f"[Scraper] No robots.txt found for {parsed.netloc}")
                return None
            
            if response.status_code != 200:
                # Can't fetch robots.txt, proceed with warning
                logger.warning(f"[Scraper] Could not fetch robots.txt: HTTP {response.status_code}")
                return None
            
            # Parse robots.txt
            rp = RobotFileParser()
            rp.parse(response.text.splitlines())
            
            # Check if scraping is allowed for all user agents
            if not rp.can_fetch("*", url):
                logger.warning(f"[Scraper] robots.txt disallows scraping: {url}")
                return ScrapeWarning(
                    type=WarningType.ROBOTS_TXT,
                    message="This website's robots.txt discourages automated scraping. Proceeding anyway."
                )
            
            return None
            
    except Exception as e:
        logger.warning(f"[Scraper] Error checking robots.txt: {e}")
        return None


def get_block_reason_for_status(status_code: int) -> BlockReason:
    """Map HTTP status codes to block reasons."""
    status_map = {
        403: BlockReason.HTTP_FORBIDDEN,
        429: BlockReason.RATE_LIMITED,
        503: BlockReason.SERVICE_UNAVAILABLE,
    }
    return status_map.get(status_code, BlockReason.HTTP_FORBIDDEN)


def detect_captcha(html: str) -> Optional[ScrapeError]:
    """
    Detect CAPTCHA elements in the HTML.
    Returns an error if CAPTCHA is detected (scraping blocked).
    """
    html_lower = html.lower()
    
    for pattern in CAPTCHA_PATTERNS:
        if pattern.lower() in html_lower:
            logger.warning(f"[Scraper] CAPTCHA detected: {pattern}")
            return ScrapeError(
                type=BlockReason.CAPTCHA_REQUIRED,
                message="This website requires CAPTCHA verification. Unable to scrape."
            )
    
    return None


def detect_bot_protection(html: str) -> Optional[ScrapeError]:
    """
    Detect bot protection/challenge pages.
    Returns an error if bot protection is detected (scraping blocked).
    """
    for pattern, provider in BOT_PROTECTION_PATTERNS:
        if pattern.lower() in html.lower():
            logger.warning(f"[Scraper] Bot protection detected: {provider} - {pattern}")
            return ScrapeError(
                type=BlockReason.BOT_PROTECTION,
                message=f"This website uses {provider} bot protection. Unable to scrape."
            )
    
    return None


def check_meta_robots(soup: BeautifulSoup) -> Optional[ScrapeWarning]:
    """
    Check for meta robots tags that discourage indexing.
    Returns a warning (we still proceed with scraping).
    """
    meta_robots = soup.find("meta", attrs={"name": "robots"})
    
    if meta_robots:
        content = meta_robots.get("content", "").lower()
        
        if "noindex" in content:
            logger.info(f"[Scraper] Meta robots noindex detected")
            return ScrapeWarning(
                type=WarningType.META_NOINDEX,
                message="This page has 'noindex' meta tag. Content may not be intended for public access."
            )
        
        if "nofollow" in content:
            logger.info(f"[Scraper] Meta robots nofollow detected")
            return ScrapeWarning(
                type=WarningType.META_NOFOLLOW,
                message="This page has 'nofollow' meta tag."
            )
    
    return None


def validate_content(data: dict) -> bool:
    """
    Validate that meaningful content was extracted.
    Returns False if content is empty or minimal (likely blocked).
    """
    has_title = bool(data.get("title"))
    has_headings = any(
        len(headings) > 0 
        for headings in data.get("headings", {}).values()
    )
    has_paragraphs = len(data.get("paragraphs", [])) > 0
    has_text_content = has_title or has_headings or has_paragraphs
    
    return has_text_content


def extract_page_data(soup: BeautifulSoup) -> dict:
    """Extract structured data from the parsed HTML."""
    return {
        "title": soup.title.string.strip() if soup.title and soup.title.string else "",
        "meta": {
            "description": (
                soup.find("meta", attrs={"name": "description"}).get("content", "").strip()
                if soup.find("meta", attrs={"name": "description"}) else ""
            ),
            "keywords": (
                soup.find("meta", attrs={"name": "keywords"}).get("content", "").strip()
                if soup.find("meta", attrs={"name": "keywords"}) else ""
            )
        },
        "headings": {
            tag: [h.get_text(strip=True) for h in soup.find_all(tag)]
            for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]
        },
        "paragraphs": [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)],
        "spans": [span.get_text(strip=True) for span in soup.find_all("span") if span.get_text(strip=True)],
        "divs": [div.get_text(strip=True) for div in soup.find_all("div") if div.get_text(strip=True)],
        "lists": {
            "unordered": [
                [li.get_text(strip=True) for li in ul.find_all("li")]
                for ul in soup.find_all("ul")
            ],
            "ordered": [
                [li.get_text(strip=True) for li in ol.find_all("li")]
                for ol in soup.find_all("ol")
            ]
        },
        "tables": [
            {
                "headers": [th.get_text(strip=True) for th in table.find_all("th")],
                "rows": [
                    [td.get_text(strip=True) for td in row.find_all("td")]
                    for row in table.find_all("tr") if row.find_all("td")
                ]
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
            {"src": iframe.get("src", ""), "title": iframe.get("title", "")}
            for iframe in soup.find_all("iframe", src=True)
            if iframe.get("src") and ("google.com/maps" in iframe.get("src", "") or "maps.google.com" in iframe.get("src", ""))
        ]
    }


async def scrape_website(url: str) -> ScrapeResult:
    """
    Scrape a website with permission detection.
    
    Returns:
        ScrapeResult with:
        - success: True if scraping succeeded
        - warnings: List of warnings (scraping proceeded anyway)
        - error: Error details if scraping was blocked
        - data: Extracted page data (if successful)
    """
    logger.info(f"[Scraper] Starting scrape for: {url}")
    warnings: list[ScrapeWarning] = []
    
    # STEP 1: Check robots.txt (WARNING only - still proceed)
    robots_warning = await check_robots_txt(url)
    if robots_warning:
        warnings.append(robots_warning)
    
    # STEP 2: Scrape with Playwright
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # Set a realistic user agent
            await page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            
            response = await page.goto(url, wait_until="load", timeout=60000)
            
            # STEP 3: Check HTTP status (BLOCK on 403/429/503)
            if response and response.status in [403, 429, 503]:
                await browser.close()
                logger.warning(f"[Scraper] HTTP {response.status} - Access denied")
                return ScrapeResult(
                    success=False,
                    url=url,
                    warnings=warnings,
                    error=ScrapeError(
                        type=get_block_reason_for_status(response.status),
                        message=f"HTTP {response.status}: Access denied by the server."
                    )
                )
            
            await page.wait_for_timeout(5000)
            html = await page.content()
            await browser.close()
            
    except Exception as e:
        error_str = str(e)
        logger.error(f"[Scraper] Playwright error: {e}")
        
        # Detect specific bot protection errors
        if "ERR_HTTP2_PROTOCOL_ERROR" in error_str:
            return ScrapeResult(
                success=False,
                url=url,
                warnings=warnings,
                error=ScrapeError(
                    type=BlockReason.BOT_PROTECTION,
                    message="This website has bot protection that is blocking access. Unable to scrape."
                )
            )
        elif "ERR_CONNECTION_REFUSED" in error_str or "ERR_NAME_NOT_RESOLVED" in error_str:
            return ScrapeResult(
                success=False,
                url=url,
                warnings=warnings,
                error=ScrapeError(
                    type=BlockReason.CONNECTION_ERROR,
                    message="Could not connect to the website. Please check if the URL is correct."
                )
            )
        elif "Timeout" in error_str:
            return ScrapeResult(
                success=False,
                url=url,
                warnings=warnings,
                error=ScrapeError(
                    type=BlockReason.TIMEOUT,
                    message="The website took too long to respond. Please try again later."
                )
            )
        else:
            return ScrapeResult(
                success=False,
                url=url,
                warnings=warnings,
                error=ScrapeError(
                    type=BlockReason.CONNECTION_ERROR,
                    message=f"Failed to connect to the website: {error_str[:200]}"
                )
            )
    
    # STEP 4: Check for CAPTCHA (BLOCK)
    captcha_error = detect_captcha(html)
    if captcha_error:
        return ScrapeResult(
            success=False,
            url=url,
            warnings=warnings,
            error=captcha_error
        )
    
    # STEP 5: Check for bot protection (BLOCK)
    bot_error = detect_bot_protection(html)
    if bot_error:
        return ScrapeResult(
            success=False,
            url=url,
            warnings=warnings,
            error=bot_error
        )
    
    # STEP 6: Parse content
    soup = BeautifulSoup(html, "html.parser")
    
    # STEP 7: Check meta robots (WARNING only)
    meta_warning = check_meta_robots(soup)
    if meta_warning:
        warnings.append(meta_warning)
    
    # STEP 8: Extract data
    data = extract_page_data(soup)
    
    # STEP 9: Validate content (BLOCK if empty)
    if not validate_content(data):
        logger.warning(f"[Scraper] No meaningful content extracted from {url}")
        return ScrapeResult(
            success=False,
            url=url,
            warnings=warnings,
            error=ScrapeError(
                type=BlockReason.EMPTY_CONTENT,
                message="No meaningful content extracted. The site may be blocking bots or the page is empty."
            )
        )
    
    logger.info(f"[Scraper] ========== SCRAPE SUCCESS: {url} ==========")
    logger.info(f"[Scraper] Title: {data['title']}")
    logger.info(f"[Scraper] Meta Description: {data['meta'].get('description', '')[:200]}")
    logger.info(f"[Scraper] Meta Keywords: {data['meta'].get('keywords', '')[:200]}")
    logger.info(f"[Scraper] Headings: {data['headings']}")
    logger.info(f"[Scraper] Paragraphs ({len(data['paragraphs'])}): {data['paragraphs'][:5]}{'...' if len(data['paragraphs']) > 5 else ''}")
    logger.info(f"[Scraper] Spans ({len(data['spans'])}): {data['spans'][:5]}{'...' if len(data['spans']) > 5 else ''}")
    logger.info(f"[Scraper] Divs ({len(data['divs'])}): {len(data['divs'])} items extracted")
    logger.info(f"[Scraper] Lists - Unordered: {len(data['lists']['unordered'])}, Ordered: {len(data['lists']['ordered'])}")
    logger.info(f"[Scraper] Tables: {len(data['tables'])} tables extracted")
    logger.info(f"[Scraper] Links ({len(data['links'])}): {data['links'][:5]}{'...' if len(data['links']) > 5 else ''}")
    logger.info(f"[Scraper] Images ({len(data['images'])}): {data['images'][:5]}{'...' if len(data['images']) > 5 else ''}")
    logger.info(f"[Scraper] Iframes: {len(data['iframes'])} iframes extracted")
    logger.info(f"[Scraper] Map Embeds: {len(data['map_embeds'])} Google Maps embeds found")
    if warnings:
        logger.info(f"[Scraper] Warnings ({len(warnings)}): {[w.type.value for w in warnings]}")
    logger.info(f"[Scraper] ========== END SCRAPE ==========")
    if warnings:
        logger.info(f"[Scraper] Completed with {len(warnings)} warning(s)")
    
    # SUCCESS
    return ScrapeResult(
        success=True,
        url=url,
        warnings=warnings,
        data=data
    )
