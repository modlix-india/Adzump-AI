import structlog
import httpx
import asyncio
from typing import List
from core.infrastructure.http_client import get_http_client as get_httpx_client
from exceptions.custom_exceptions import GoogleAutocompleteException

logger = structlog.get_logger(__name__)

AUTOCOMPLETE_URL = "http://suggestqueries.google.com/complete/search"


async def fetch_autocomplete_suggestions(
    seed_keyword: str,
    max_results: int = 5,
    language: str = "en",
    client: httpx.AsyncClient | None = None,
) -> List[str]:
    """Fetch keyword suggestions from Google Autocomplete API."""
    try:
        params = {
            "client": "firefox",
            "q": seed_keyword,
            "hl": language,
        }

        if client is None:
            client = get_httpx_client()
        response = await client.get(AUTOCOMPLETE_URL, params=params, timeout=5.0)
        response.raise_for_status()

        # Response format: [query, [suggestions], ...]
        data = response.json()
        suggestions = data[1] if len(data) > 1 else []

        # Limit results
        limited_suggestions = suggestions[:max_results]

        logger.debug(
            f"Autocomplete suggestions for '{seed_keyword}'",
            count=len(limited_suggestions),
        )

        return limited_suggestions

    except Exception as e:
        logger.warning(f"Autocomplete error for '{seed_keyword}': {e}")
        raise GoogleAutocompleteException(
            message=f"Autocomplete failed for '{seed_keyword}'",
            details={"error": str(e)},
        )


# TODO: Move to adapters/google/autocomplete.py. It's an external Google API call,
# should follow adapter pattern like keyword_planner.py.
async def batch_fetch_autocomplete_suggestions(
    seed_keywords: List[str],
    max_results_per_seed: int = 5,
    language: str = "en",
) -> List[str]:
    """Fetch autocomplete suggestions for multiple seed keywords in parallel."""
    logger.info(f"Fetching autocomplete suggestions for {len(seed_keywords)} seeds")

    # Get client once for the batch
    client = get_httpx_client()

    # Fetch in parallel
    tasks = [
        fetch_autocomplete_suggestions(
            seed, max_results_per_seed, language, client=client
        )
        for seed in seed_keywords
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten and deduplicate
    all_suggestions = []
    for result in results:
        if isinstance(result, list):
            all_suggestions.extend(result)
        elif isinstance(result, Exception):
            logger.warning("Individual seed expansion failed", error=str(result))

    # Remove duplicates while preserving order
    seen = set()
    unique_suggestions = []
    for suggestion in all_suggestions:
        suggestion_lower = suggestion.lower()
        if suggestion_lower not in seen:
            seen.add(suggestion_lower)
            unique_suggestions.append(suggestion)

    logger.info(
        "Autocomplete expansion complete",
        total_suggestions=len(unique_suggestions),
        from_seeds=len(seed_keywords),
    )

    return unique_suggestions
