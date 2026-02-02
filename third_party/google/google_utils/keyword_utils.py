import re
import structlog
import json
import httpx
import asyncio
from typing import List, Dict, Set, Any
from utils.text_utils import normalize_text
from models.keyword_model import (
    OptimizedKeyword,
    NegativeKeyword,
)

logger = structlog.get_logger(__name__)
WORD_PATTERN = re.compile(r"\w+")
RETRY_ATTEMPTS = 3
RETRY_DELAY = 5


class KeywordUtils:
    @staticmethod
    def parse_and_normalize_seed_keywords(raw: str, limit: int) -> List[str]:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                keywords = parsed
            else:
                raise ValueError("Response not a list")
        except Exception:
            parts = re.findall(r'"([^"]+)"', raw)
            if not parts:
                parts = re.split(r"[\n,•;]+", raw)
            keywords = [p.strip().strip("\"'") for p in parts if p.strip()]

        return KeywordUtils.normalize_keywords(keywords, limit)

    @staticmethod
    def normalize_keywords(keywords: List[str], limit: int) -> List[str]:
        normalized, seen = [], set()
        for kw in keywords:
            if not isinstance(kw, str):
                continue
            k = normalize_text(kw)
            if 2 <= len(k) and k not in seen:
                normalized.append(k)
                seen.add(k)
        return normalized[:limit]

    @staticmethod
    def filter_and_validate_negatives(
        negatives_raw: List[Dict[str, str]],
        positive_keywords: List[OptimizedKeyword],
        safety_patterns: List[re.Pattern],
    ) -> List[NegativeKeyword]:
        """Filter and validate negative keywords."""
        from utils.text_utils import normalize_text

        cleaned_negatives: List[NegativeKeyword] = []
        seen_keywords: Set[str] = set()

        positive_keywords_lower = {kw.keyword.lower() for kw in positive_keywords}
        positive_tokens = set()
        for kw in positive_keywords_lower:
            positive_tokens.update(WORD_PATTERN.findall(kw))

        for item in negatives_raw:
            if not isinstance(item, dict) or "keyword" not in item:
                continue

            kw = normalize_text(item.get("keyword", ""))
            reason = item.get("reason", "Budget protection")

            kw_len = len(kw)
            if not kw or kw_len < 2 or kw_len > 50 or kw in seen_keywords:
                continue

            if any(pattern.search(kw) for pattern in safety_patterns):
                continue

            kw_lower = kw.lower()
            if kw_lower in positive_keywords_lower:
                continue

            kw_tokens = set(WORD_PATTERN.findall(kw_lower))
            if kw_tokens:
                overlap_ratio = len(kw_tokens & positive_tokens) / len(kw_tokens)
                if overlap_ratio >= 0.8:
                    continue

            seen_keywords.add(kw)
            negative = NegativeKeyword(keyword=kw, reason=reason)
            cleaned_negatives.append(negative)

            if len(cleaned_negatives) >= 40:
                break

        return cleaned_negatives


async def retry_post_with_backoff(
    client: httpx.AsyncClient,
    endpoint: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    max_attempts: int = RETRY_ATTEMPTS,
    base_delay: float = RETRY_DELAY,
) -> httpx.Response:
    """Reusable retry for POST with exponential backoff and Google Ads quota hints."""
    for attempt in range(max_attempts):
        try:
            response = await client.post(endpoint, headers=headers, json=payload)

            if response.status_code == 200:
                return response

            # Retry on server/quota errors
            if response.status_code in [429, 500, 503] and attempt < max_attempts - 1:
                wait_time = base_delay * (2**attempt)

                # Parse Google Ads retry hint if available
                try:
                    error_data = response.json()
                    retry_hint = (
                        error_data.get("error", {})
                        .get("details", [{}])[0]
                        .get("quotaErrorDetails", {})
                        .get("retryDelay")
                    )
                    if retry_hint:
                        wait_time = int(retry_hint.rstrip("s"))
                except (KeyError, ValueError, IndexError):
                    pass  # Fallback to exponential

                logger.warning(
                    f"API error {response.status_code}, retrying in {wait_time}s (attempt {attempt + 1}/{max_attempts})"
                )
                await asyncio.sleep(wait_time)
                continue

            logger.error(f"API error {response.status_code}: {response.text}")
            response.raise_for_status()

        except httpx.TimeoutException:
            if attempt < max_attempts - 1:
                wait_time = base_delay * (2**attempt)
                logger.warning(
                    f"Timeout, retrying in {wait_time}s (attempt {attempt + 1}/{max_attempts})"
                )
                await asyncio.sleep(wait_time)
            else:
                raise
        except httpx.HTTPStatusError:
            raise
        except Exception as e:
            if attempt < max_attempts - 1:
                wait_time = base_delay * (2**attempt)
                logger.warning(
                    f"Request error, retrying in {wait_time}s (attempt {attempt + 1}/{max_attempts}): {str(e)[:100]}"
                )
                await asyncio.sleep(wait_time)
            else:
                raise

    raise RuntimeError("POST failed after all retry attempts")
