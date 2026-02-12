import asyncio

from structlog import get_logger

from core.infrastructure.context import auth_context
from core.infrastructure.http_client import http_request
from adapters.google.client import (
    GoogleAdsClient,
    _raise_google_error,
    _extract_retry_delay,
)

logger = get_logger(__name__)


class GoogleKeywordPlannerAdapter:
    CHUNK_SIZE = 15
    CHUNK_DELAY = 0.5
    DEFAULT_LOCATION_IDS = ["geoTargetConstants/2356"]
    DEFAULT_LANGUAGE_ID = 1000
    MIN_KEYWORD_LENGTH = 2
    MAX_KEYWORD_WORDS = 6

    def __init__(self):
        self.client = GoogleAdsClient()

    async def generate_keyword_ideas(
        self,
        customer_id: str,
        login_customer_id: str,
        seed_keywords: list[str],
        url: str | None = None,
        location_ids: list[str] | None = None,
        language_id: int = DEFAULT_LANGUAGE_ID,
    ) -> list[dict]:
        """Fetch keyword ideas from Google Ads Keyword Planner API.

        Seeds are chunked and processed sequentially. Results are deduplicated
        by keyword text, keeping the entry with the highest search volume.
        """
        location_ids = location_ids or self.DEFAULT_LOCATION_IDS
        token = self.client._get_token(auth_context.client_code)
        headers = self.client._headers(token, login_customer_id)
        endpoint = (
            f"{self.client.BASE_URL}/{self.client.API_VERSION}"
            f"/customers/{customer_id}:generateKeywordIdeas"
        )

        seen: dict[str, dict] = {}

        for i in range(0, len(seed_keywords), self.CHUNK_SIZE):
            chunk = seed_keywords[i : i + self.CHUNK_SIZE]
            chunk_num = i // self.CHUNK_SIZE + 1

            payload = _build_payload(chunk, url, location_ids, language_id)
            logger.info("keyword_planner_chunk", chunk=chunk_num, seeds=len(chunk))

            response = await http_request(
                "POST",
                endpoint,
                headers=headers,
                json=payload,
                error_handler=_raise_google_error,
                retry_delay_parser=_extract_retry_delay,
            )

            for idea in response.json().get("results", []):
                parsed = _parse_keyword_idea(idea)
                if parsed:
                    _deduplicate(seen, parsed)

            if i + self.CHUNK_SIZE < len(seed_keywords):
                await asyncio.sleep(self.CHUNK_DELAY)

        results = sorted(seen.values(), key=lambda k: k["volume"], reverse=True)
        logger.info("keyword_planner_done", total=len(results))
        return results


def _build_payload(
    chunk: list[str],
    url: str | None,
    location_ids: list[str],
    language_id: int,
) -> dict:
    payload = {
        "language": f"languageConstants/{language_id}",
        "geoTargetConstants": list(location_ids),
        "includeAdultKeywords": False,
        "keywordPlanNetwork": "GOOGLE_SEARCH_AND_PARTNERS",
    }
    if url and url.strip():
        payload["keywordAndUrlSeed"] = {"keywords": chunk, "url": url.strip()}
    else:
        payload["keywordSeed"] = {"keywords": chunk}
    return payload


def _parse_keyword_idea(idea: dict) -> dict | None:
    text = (idea.get("text") or "").strip().lower()
    if len(text) < GoogleKeywordPlannerAdapter.MIN_KEYWORD_LENGTH:
        return None
    if len(text.split()) > GoogleKeywordPlannerAdapter.MAX_KEYWORD_WORDS:
        return None

    metrics = idea.get("keywordIdeaMetrics", {})
    return {
        "keyword": text,
        "volume": int(metrics.get("avgMonthlySearches", 0) or 0),
        "competition": metrics.get("competition", "UNKNOWN"),
        "competitionIndex": float(metrics.get("competitionIndex", 0) or 0) / 100.0,
    }


def _deduplicate(seen: dict[str, dict], entry: dict) -> None:
    keyword = entry["keyword"]
    existing = seen.get(keyword)
    if existing is None or entry["volume"] > existing["volume"]:
        seen[keyword] = entry
