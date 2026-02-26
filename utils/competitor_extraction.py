import json
from typing import Dict, List, Any
from urllib.parse import urlparse
from structlog import get_logger
from services import openai_client
from utils import prompt_loader

logger = get_logger(__name__)


async def select_strategic_pages(
    links: List[Dict[str, Any]],
    base_url: str,
    model: str = "gpt-4o-mini",
    max_pages: int = 5,
) -> List[str]:
    """Use AI to intelligently select the most valuable pages for keyword analysis."""
    if not links:
        return []

    # Reduce noise: simplify links for the LLM
    candidate_links = []
    for link in links:
        href = link.get("href", "")
        text = link.get("text", "").strip()
        if href and text and not href.startswith(("#", "mailto:", "tel:")):
            candidate_links.append({"url": href, "anchor": text})

    prompt = prompt_loader.format_prompt(
        "competitor/link_selector_prompt.txt",
        base_url=base_url,
        links_json=json.dumps(candidate_links[:100]),  # Top 100 links only
        max_pages=max_pages,
    )

    try:
        resp = await openai_client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            response_format={"type": "json_object"},
        )
        raw = json.loads(resp.choices[0].message.content.strip())
        selection = raw.get("selection") or []
        urls = []
        for item in selection:
            u = item.get("url") if isinstance(item, dict) else str(item)
            if u:
                urls.append(u)
        logger.info("competitor.ai_links_selected", urls=urls, count=len(urls))
        return urls[:max_pages]
    except Exception as e:
        logger.warning("competitor.ai_link_selector_failed", error=str(e))
        return []


def merge_page_data(pages: List[Dict]) -> List[Dict]:
    """
    Clean and structure multiple scraped pages into a high-signal list.

    Instead of a 'flat blob', this preserves the source URL and specific
    headings for each page, allowing the AI to distinguish between the
    Homepage and deep product pages.
    """
    cleaned_pages = []
    for page in pages:
        if not page:
            continue

        url = page.get("url", "")
        # Extract path relative to domain for cleaner keys
        path = urlparse(url).path or "/"

        cleaned = {
            "page": path,
            "title": page.get("title", ""),
            "meta_description": page.get("meta", {}).get("description", ""),
            "h1": page.get("headings", {}).get("h1", []),
            "h2": page.get("headings", {}).get("h2", [])[:5],
            "h3": page.get("headings", {}).get("h3", [])[:5],
            "key_content": " ".join(page.get("paragraphs", [])[:5])[:500],
        }
        cleaned_pages.append(cleaned)

    return cleaned_pages
