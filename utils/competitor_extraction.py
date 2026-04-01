from __future__ import annotations
import json
from typing import Any
from urllib.parse import urlparse
from structlog import get_logger
from services import openai_client
from utils import prompt_loader
from models.competitor_model import Competitor

logger = get_logger(__name__)


async def select_strategic_pages(
    links: list[dict[str, Any]],
    base_url: str,
    model: str = "gpt-4o-mini",
    max_pages: int = 5,
) -> list[str]:
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
            messages=[
                {
                    "role": "system",
                    "content": "You are a specialized Competitive Intelligence Analyst focusing on strategic link selection.",
                },
                {"role": "user", "content": prompt},
            ],
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


def merge_page_data(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def filter_already_analyzed_competitors(
    raw_competitors: list[Competitor],
    existing_analysis: list[Competitor],
    force_fresh_analysis: bool = False,
) -> tuple[list[Competitor], list[Competitor]]:
    """
    Categorize competitors into 'to discover' and 'already done' based on existing storage data.

    Returns:
        tuple: (list_of_raw_to_discover, list_of_competitor_objects_already_done)
    """
    if not raw_competitors:
        return [], []

    # 1. Map raw_competitors URLs to see what the user actually wants NOW
    desired_urls = {c.url for c in raw_competitors if c.url}

    # 2. Identify "already-done" competitors if not forcing fresh discovery
    already_done_map: dict[str, Competitor] = {}
    if not force_fresh_analysis and existing_analysis:
        for c_obj in existing_analysis:
            # Only keep if they have keywords AND are in the current desired list
            if c_obj.extracted_keywords and c_obj.url in desired_urls:
                already_done_map[c_obj.url] = c_obj

    # 3. Filter for "delta" discovery
    to_discover = []
    for raw_c in raw_competitors:
        if raw_c.url and raw_c.url not in already_done_map:
            to_discover.append(raw_c)

    return to_discover, list(already_done_map.values())
