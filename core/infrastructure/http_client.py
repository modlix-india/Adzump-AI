import asyncio
import random
from collections.abc import Callable

import httpx
import structlog

logger = structlog.get_logger(__name__)

_client: httpx.AsyncClient | None = None

RETRYABLE_STATUS_CODES = frozenset({429, 500, 503})


def init_http_client():
    global _client
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(60, connect=10),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )


async def close_http_client():
    global _client
    if _client:
        await _client.aclose()
        _client = None


def get_http_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("HTTP client not initialized")
    return _client


async def http_request(
    method: str,
    url: str,
    *,
    max_attempts: int = 3,
    base_delay: float = 2.0,
    error_handler: Callable[[httpx.Response], None] | None = None,
    retry_delay_parser: Callable[[httpx.Response, float], float] | None = None,
    **kwargs,
) -> httpx.Response:
    """HTTP request with built-in retry (exponential backoff + jitter)."""
    client = get_http_client()

    for attempt in range(max_attempts):
        try:
            response = await client.request(method, url, **kwargs)

            if response.is_success:
                return response

            is_last = attempt == max_attempts - 1
            if response.status_code not in RETRYABLE_STATUS_CODES or is_last:
                if error_handler:
                    error_handler(response)
                response.raise_for_status()

            delay = _compute_delay(attempt, base_delay, response, retry_delay_parser)
            logger.warning(
                "http_retry",
                status=response.status_code,
                attempt=attempt + 1,
                retry_in=round(delay, 2),
            )
            await asyncio.sleep(delay)

        except httpx.TimeoutException:
            if attempt == max_attempts - 1:
                raise
            delay = _compute_delay(attempt, base_delay)
            logger.warning(
                "http_timeout_retry", attempt=attempt + 1, retry_in=round(delay, 2)
            )
            await asyncio.sleep(delay)

        except httpx.HTTPStatusError:
            raise

    raise RuntimeError("Request failed after all retry attempts")


def _compute_delay(
    attempt: int,
    base_delay: float,
    response: httpx.Response | None = None,
    retry_delay_parser: Callable[[httpx.Response, float], float] | None = None,
) -> float:
    delay = base_delay * (2**attempt)
    if response and retry_delay_parser:
        delay = retry_delay_parser(response, delay)
    return delay + random.uniform(0, delay * 0.25)
