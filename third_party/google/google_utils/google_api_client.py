import asyncio
import httpx
import structlog
from typing import Dict, Any
from exceptions.custom_exceptions import (
    GoogleAdsAuthException,
    GoogleAdsValidationException,
)

logger = structlog.get_logger(__name__)

RETRY_ATTEMPTS = 3
RETRY_DELAY = 5


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
            _handle_response_status(response)
            return response

        except httpx.TimeoutException:
            if attempt < max_attempts - 1:
                wait_time = base_delay * (2**attempt)
                logger.warning(
                    f"Timeout, retrying in {wait_time}s (attempt {attempt + 1}/{max_attempts})"
                )
                await asyncio.sleep(wait_time)
            else:
                raise

        except httpx.HTTPStatusError as e:
            # Retry on server/quota errors (429, 500, 503)
            if e.response.status_code in [429, 500, 503] and attempt < max_attempts - 1:
                wait_time = _parse_retry_delay(e.response, base_delay * (2**attempt))
                logger.warning(
                    f"API error {e.response.status_code}, retrying in {wait_time}s (attempt {attempt + 1}/{max_attempts})"
                )
                await asyncio.sleep(wait_time)
            else:
                raise

        except (GoogleAdsAuthException, GoogleAdsValidationException):
            # Don't retry permanent errors - fail immediately
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


def _handle_response_status(response: httpx.Response) -> None:
    """Check response status and raise appropriate exceptions for permanent errors."""
    if response.status_code == 200:
        return  # Success

    # Fail fast on permanent authentication/authorization errors
    if response.status_code in [401, 403]:
        logger.error(f"Permanent Auth error {response.status_code}: {response.text}")
        raise GoogleAdsAuthException(
            message=f"Google Ads API authentication failed ({response.status_code})",
            details={"response": response.text},
        )

    # Fail fast on malformed requests
    if response.status_code == 400:
        logger.error(f"Permanent Validation error 400: {response.text}")
        raise GoogleAdsValidationException(
            message="Google Ads API request validation failed (400)",
            details={"response": response.text},
        )

    # For other errors, raise HTTPStatusError to trigger retry logic
    logger.error(f"API error {response.status_code}: {response.text}")
    response.raise_for_status()


def _parse_retry_delay(response: httpx.Response, base_delay: float) -> float:
    """Extract retry delay from Google Ads quota error response, or use exponential backoff."""
    try:
        error_data = response.json()
        retry_hint = (
            error_data.get("error", {})
            .get("details", [{}])[0]
            .get("quotaErrorDetails", {})
            .get("retryDelay")
        )
        if retry_hint:
            return int(retry_hint.rstrip("s"))
    except (KeyError, ValueError, IndexError):
        pass
    return base_delay
