import asyncio
from difflib import SequenceMatcher
from typing import Awaitable, Callable

import structlog
from openai import RateLimitError, APIError

logger = structlog.get_logger(__name__)


def deduplicate_items(items: list[str], similarity_threshold: float) -> list[str]:
    if not items:
        return []

    # Pass 1: exact dedup
    seen_lower: set[str] = set()
    unique: list[str] = []
    for item in items:
        key = item.lower().strip()
        if key not in seen_lower:
            seen_lower.add(key)
            unique.append(item)

    # Pass 2: similarity-based dedup
    final: list[str] = []
    for item in unique:
        is_similar = False
        for existing in final:
            ratio = SequenceMatcher(None, item.lower(), existing.lower()).ratio()
            if ratio >= similarity_threshold:
                is_similar = True
                logger.debug(
                    "Removed similar item",
                    removed=item,
                    similar_to=existing,
                    similarity=round(ratio, 2),
                )
                break
        if not is_similar:
            final.append(item)

    return final


def filter_by_length(items: list[str], min_chars: int, max_chars: int) -> list[str]:
    """Keep only items whose character length is within [min_chars, max_chars]."""
    return [item for item in items if min_chars <= len(item) <= max_chars]


async def run_with_retry(
    llm_fn: Callable[[float], Awaitable[list[str]]],
    min_count: int,
    max_retries: int,
    temp_start: float,
    label: str = "items",
) -> list[str]:
    all_raw: list[str] = []

    for attempt in range(max_retries):
        temperature = temp_start + (attempt * 0.1)
        logger.info(
            f"[AdTextUtils] Attempt {attempt + 1}/{max_retries}",
            label=label,
            temperature=temperature,
        )

        try:
            raw_items = await llm_fn(temperature)
            all_raw.extend(raw_items)

            logger.info(
                f"[AdTextUtils] Attempt {attempt + 1} raw count",
                label=label,
                count=len(raw_items),
                total_pool=len(all_raw),
            )

            if len(raw_items) >= min_count:
                logger.info(
                    f"[AdTextUtils] Quality met on attempt {attempt + 1}",
                    label=label,
                )
                return all_raw

            logger.warning(
                "[AdTextUtils] Quality failure — retrying",
                label=label,
                got=len(raw_items),
                need=min_count,
                attempt=attempt + 1,
            )

        except (RateLimitError, APIError) as api_err:
            wait = 2**attempt  # exponential backoff: 1s, 2s, 4s
            logger.warning(
                "[AdTextUtils] API error — backing off",
                label=label,
                error=str(api_err),
                wait_seconds=wait,
                attempt=attempt + 1,
            )
            await asyncio.sleep(wait)

    logger.warning(
        "[AdTextUtils] All attempts exhausted — returning pool for rescue",
        label=label,
        pool_size=len(all_raw),
    )
    return all_raw


def rescue_pool_fallback(
    all_items: list[str],
    min_chars: int,
    max_chars: int,
    similarity_threshold: float,
    min_count: int,
    label: str = "items",
) -> list[str]:
    relaxed_min = int(min_chars * 0.9)
    relaxed_max = int(max_chars * 1.1)

    filtered = filter_by_length(all_items, relaxed_min, relaxed_max)
    deduped = deduplicate_items(filtered, similarity_threshold)
    result = sorted(deduped, key=len, reverse=True)[:min_count]

    logger.info(
        "[AdTextUtils] Rescue pool result",
        label=label,
        pool_size=len(all_items),
        after_filter=len(filtered),
        after_dedup=len(deduped),
        final=len(result),
        needed=min_count,
    )

    if len(result) < min_count:
        logger.critical(
            "[AdTextUtils] CRITICAL: Rescue pool could not meet minimum",
            label=label,
            got=len(result),
            needed=min_count,
        )

    return result
