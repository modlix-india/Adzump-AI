"""Competitor finder — LLM-only agent that identifies competitors from website summary."""

import json

from structlog import get_logger

from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt

logger = get_logger(__name__)


async def find_competitors(website_summary: dict) -> list[dict]:
    """Identify competitors from a website summary via LLM.

    Returns [{"name": str, "domain": str | None}, ...] capped at 8.
    Returns [] on failure (non-blocking).
    """
    business_url = website_summary.get("business_url", "")
    business_type = website_summary.get("business_type", "")
    summary = website_summary.get("final_summary") or website_summary.get("summary", "")
    location = _extract_location(website_summary)

    if not summary:
        logger.warning("competitor_find_skipped", reason="no summary")
        return []

    prompt = load_prompt("chatv2/find_competitors.txt")
    system_msg = prompt.format(
        business_url=business_url or "Not specified",
        business_type=business_type,
        summary=summary,
        location=location or "Not specified",
    )

    try:
        response = await chat_completion(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": "Identify the top competitors for this business."},
            ],
            model="gpt-4o-mini",
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw = json.loads(response.choices[0].message.content)
        competitors = raw.get("competitors", [])
        return [
            {
                "name": c["name"],
                "domain": c.get("domain"),
                "url": f"https://{c['domain']}" if c.get("domain") else None,
            }
            for c in competitors
            if isinstance(c, dict) and c.get("name")
        ][:8]
    except Exception:
        logger.warning("competitor_find_failed", exc_info=True)
        return []


def _extract_location(summary: dict) -> str:
    """Pull location string from website summary."""
    loc = summary.get("location")
    if loc:
        if isinstance(loc, dict):
            result = loc.get("area_location") or loc.get("product_location") or ""
            if result:
                return result
        else:
            return str(loc)

    geo_targets = summary.get("suggested_geo_targets")
    if geo_targets and isinstance(geo_targets, list):
        names = [str(t["name"]) for t in geo_targets if isinstance(t, dict) and t.get("name")]
        if names:
            return ", ".join(names[:3])

    return ""
