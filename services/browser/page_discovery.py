import json
from typing import List, Dict
from urllib.parse import urlparse, urljoin
from structlog import get_logger  # type: ignore

from config.scraper_config import ScraperConfig
from services.openai_client import chat_completion
from utils import prompt_loader

logger = get_logger(__name__)


class PageDiscovery:
    OPENAI_MODEL = "gpt-4o-mini"

    def __init__(self, max_pages: int = ScraperConfig.MAX_PAGES_TO_SCRAPE):
        self.max_pages = max_pages

    async def discover_pages(
        self, links: List[Dict[str, str]], base_url: str
    ) -> List[str]:
        # Filter to internal links only
        internal_links = self._filter_internal_links(links, base_url)

        if not internal_links:
            logger.info("[PageDiscovery] No internal links found, using fallback paths")
            return self._get_fallback_urls(base_url)

        # Prepare links for LLM
        link_descriptions = self._format_links_for_llm(internal_links)

        try:
            prompt = prompt_loader.format_prompt(
                "page_discovery_prompt.txt",
                url=base_url,
                links=link_descriptions,
                max_pages=self.max_pages,
            )

            response = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.OPENAI_MODEL,
                max_tokens=200,
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content.strip())
            selected_paths = result.get("pages", [])[: self.max_pages]

            # Convert paths to absolute URLs
            absolute_urls = [
                self._to_absolute_url(path, base_url) for path in selected_paths
            ]

            logger.info(
                "[PageDiscovery] LLM selected pages",
                count=len(absolute_urls),
                pages=absolute_urls,
            )
            return absolute_urls

        except Exception as e:
            logger.warning(f"[PageDiscovery] LLM selection failed: {e}, using fallback")
            return self._get_fallback_urls(base_url)

    def _filter_internal_links(
        self, links: List[Dict[str, str]], base_url: str
    ) -> List[Dict[str, str]]:
        parsed_base = urlparse(base_url)
        base_domain = parsed_base.netloc

        internal = []
        for link in links:
            href = link.get("href", "")

            # Skip empty, anchor-only, or javascript links
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue

            # Check if internal
            if href.startswith("/"):
                internal.append(link)
            elif href.startswith(("http://", "https://")):
                parsed = urlparse(href)
                if parsed.netloc == base_domain:
                    internal.append(link)

        return internal

    def _format_links_for_llm(self, links: List[Dict[str, str]]) -> str:
        """Format links as text for LLM prompt."""
        formatted = []
        for i, link in enumerate(links[:50], 1):  # Limit to 50 links
            text = link.get("text", "").strip() or "(no text)"
            href = link.get("href", "")
            formatted.append(f"{i}. {text} -> {href}")
        return "\n".join(formatted)

    def _to_absolute_url(self, path: str, base_url: str) -> str:
        """Convert relative path to absolute URL."""
        if path.startswith(("http://", "https://")):
            return path
        return urljoin(base_url, path)

    def _get_fallback_urls(self, base_url: str) -> List[str]:
        """Get fallback URLs when no links or LLM fails."""
        return [urljoin(base_url, path) for path in ScraperConfig.FALLBACK_PATHS]

    def get_fallback_paths(self) -> List[str]:
        """Get fallback paths for empty homepage."""
        return ScraperConfig.FALLBACK_PATHS.copy()
