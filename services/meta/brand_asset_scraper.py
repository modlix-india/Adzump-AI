from services.scraper_service import scrape_website
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import os
import hashlib
import requests


LOGO_CACHE_DIR = "services/meta/logo_cache"


class BrandAssetScraper:

    @staticmethod
    async def extract_assets(url: str) -> dict:
        os.makedirs(LOGO_CACHE_DIR, exist_ok=True)

        cache_key = BrandAssetScraper._cache_key(url)
        cached_logo = BrandAssetScraper._load_from_cache(cache_key)
        if cached_logo:
            return cached_logo

        raw_data = await scrape_website(url)

        html = await BrandAssetScraper._fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")

        candidates = []

        # -------------------------------------------------
        # 1. META / OG IMAGES (HIGH CONFIDENCE)
        # -------------------------------------------------
        for meta in soup.find_all("meta"):
            prop = (meta.get("property") or meta.get("name") or "").lower()
            content = meta.get("content")

            if not content:
                continue

            if prop in ["og:logo"]:
                candidates.append(
                    BrandAssetScraper._candidate(url, content, 0.95, "meta")
                )

            if prop == "og:image" and "logo" in content.lower():
                candidates.append(
                    BrandAssetScraper._candidate(url, content, 0.9, "og:image")
                )

        # -------------------------------------------------
        # 2. HEADER / NAV IMG + SVG (PRIMARY SOURCE)
        # -------------------------------------------------
        for container in soup.find_all(["header", "nav"]):
            for img in container.find_all("img", src=True):
                if BrandAssetScraper._is_valid_logo(img):
                    candidates.append(
                        BrandAssetScraper._candidate(
                            url, img["src"], 0.9, "header-img"
                        )
                    )

            svg = container.find("svg")
            if svg:
                return BrandAssetScraper._cache_and_return(
                    cache_key,
                    {
                        "logo": {
                            "inline_svg": str(svg),
                            "format": "svg",
                            "source": "header-svg",
                            "confidence": 0.92
                        }
                    }
                )

        # -------------------------------------------------
        # 3. ICON FALLBACK (LOWER CONFIDENCE)
        # -------------------------------------------------
        for link in soup.find_all("link", href=True):
            rel = " ".join(link.get("rel", [])).lower()
            href = link.get("href")

            if any(k in rel for k in ["icon", "apple-touch-icon"]):
                candidates.append(
                    BrandAssetScraper._candidate(url, href, 0.6, "icon")
                )

        # -------------------------------------------------
        # 4. PICK BEST CANDIDATE
        # -------------------------------------------------
        if not candidates:
            return {"logo": None}

        best = max(candidates, key=lambda x: x["logo"]["confidence"])
        return BrandAssetScraper._cache_and_return(cache_key, best)

    # -----------------------------------------------------
    # Helpers
    # -----------------------------------------------------

    @staticmethod
    def _is_valid_logo(img) -> bool:
        src = img.get("src", "").lower()
        alt = (img.get("alt") or "").lower()
        classes = " ".join(img.get("class", [])).lower()

        reject_keywords = [
            "hero", "banner", "cover", "background", "carousel",
            "slider", "thumbnail", "product", "illustration"
        ]

        if any(k in src for k in reject_keywords):
            return False

        if any(k in alt for k in reject_keywords):
            return False

        return any(k in src or k in alt or k in classes for k in ["logo", "brand"])

    @staticmethod
    def _candidate(base_url, src, confidence, source):
        full_url = urljoin(base_url, src)
        ext = os.path.splitext(urlparse(full_url).path)[1].replace(".", "")

        return {
            "logo": {
                "url": full_url,
                "format": ext or "unknown",
                "source": source,
                "confidence": confidence
            }
        }

    @staticmethod
    async def _fetch_html(url: str) -> str:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="load", timeout=60000)
            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()
            return html

    @staticmethod
    def _cache_key(url: str) -> str:
        return hashlib.md5(url.encode()).hexdigest()

    @staticmethod
    def _cache_path(key: str) -> str:
        return os.path.join(LOGO_CACHE_DIR, f"{key}.json")

    @staticmethod
    def _load_from_cache(key: str):
        path = BrandAssetScraper._cache_path(key)
        if os.path.exists(path):
            with open(path, "r") as f:
                import json
                return json.load(f)
        return None

    @staticmethod
    def _cache_and_return(key: str, data: dict):
        path = BrandAssetScraper._cache_path(key)
        with open(path, "w") as f:
            import json
            json.dump(data, f)
        return data
