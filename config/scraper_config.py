import os
from typing import List, Tuple, Dict
from models.business_model import BlockReason


class ScraperConfig:
    # ===== CONCURRENCY =====
    MAX_CONCURRENT_BROWSERS: int = int(os.getenv("SCRAPER_MAX_BROWSERS", "3"))
    MAX_PAGES_PER_BROWSER: int = int(os.getenv("SCRAPER_MAX_PAGES_PER_BROWSER", "10"))
    MAX_CONCURRENT_REQUESTS: int = int(os.getenv("SCRAPER_MAX_CONCURRENT", "100"))

    # ===== TIMEOUTS (milliseconds) =====
    PAGE_TIMEOUT_MS: int = int(os.getenv("SCRAPER_TIMEOUT_MS", "60000"))
    PAGE_WAIT_MS: int = int(os.getenv("SCRAPER_WAIT_MS", "3000"))
    SCREENSHOT_WAIT_MS: int = int(os.getenv("SCREENSHOT_WAIT_MS", "2000"))

    # ===== USER AGENT =====
    USER_AGENT: str = os.getenv(
        "SCRAPER_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )

    # ===== CAPTCHA DETECTION PATTERNS =====
    CAPTCHA_PATTERNS: List[str] = [
        "g-recaptcha",
        "h-captcha",
        "cf-turnstile",
        'id="captcha"',
        'class="captcha"',
        "recaptcha",
        "hcaptcha",
    ]

    # ===== BOT PROTECTION PATTERNS (pattern, provider) =====
    BOT_PROTECTION_PATTERNS: List[Tuple[str, str]] = [
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

    # ===== HTTP STATUS TO BLOCK REASON MAPPING =====
    STATUS_BLOCK_MAP: Dict[int, BlockReason] = {
        403: BlockReason.HTTP_FORBIDDEN,
        429: BlockReason.RATE_LIMITED,
        503: BlockReason.SERVICE_UNAVAILABLE,
    }

    # ===== PAGE DISCOVERY =====
    MAX_PAGES_TO_SCRAPE: int = int(os.getenv("SCRAPER_MAX_PAGES", "5"))
    FALLBACK_PATHS: List[str] = [
        "/about",
        "/services",
        "/products",
        "/contact",
        "/team",
    ]
