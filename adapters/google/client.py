import os
import time

import httpx
import structlog

from oserver.services.connection import fetch_google_api_token_simple
from core.infrastructure.http_client import http_request

from exceptions.custom_exceptions import (
    GoogleAPIException,
    GoogleAdsAuthException,
    GoogleAdsValidationException,
)

logger = structlog.get_logger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

_cached_google_api_token: str | None = None
_google_api_token_expiry: float = 0


class GoogleAdsClient:
    BASE_URL = "https://googleads.googleapis.com"
    API_VERSION = "v21"

    def __init__(self) -> None:
        self.developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")

    async def get(self, endpoint: str, client_code: str) -> dict:
        token = self._get_google_api_token(client_code)
        url = f"{self.BASE_URL}/{self.API_VERSION}/{endpoint}"
        response = await http_request(
            "GET",
            url,
            headers=self._build_auth_headers(token),
            error_handler=_raise_google_error,
        )
        return response.json()

    async def search(
        self,
        query: str,
        customer_id: str,
        login_customer_id: str,
        client_code: str,
    ) -> list:
        """Execute GAQL query via googleAds:search."""
        token = self._get_google_api_token(client_code)
        url = f"{self.BASE_URL}/{self.API_VERSION}/customers/{customer_id}/googleAds:search"
        response = await http_request(
            "POST",
            url,
            headers=self._build_auth_headers(token, login_customer_id),
            json={"query": query},
            error_handler=_raise_google_error,
        )
        return response.json().get("results", [])

    async def mutate(
        self,
        customer_id: str,
        mutate_payload: dict,
        client_code: str,
        login_customer_id: str | None = None,
    ) -> dict:
        """Execute mutate operations via googleAds:mutate."""
        token = self._get_google_api_token(client_code)
        url = f"{self.BASE_URL}/{self.API_VERSION}/customers/{customer_id}/googleAds:mutate"
        response = await http_request(
            "POST",
            url,
            headers=self._build_auth_headers(token, login_customer_id),
            json=mutate_payload,
            error_handler=_raise_google_error,
        )
        return response.json()

    async def search_stream(
        self, query: str, customer_id: str, login_customer_id: str, client_code: str
    ) -> list:
        token = self._get_google_api_token(client_code)
        url = f"{self.BASE_URL}/{self.API_VERSION}/customers/{customer_id}/googleAds:searchStream"

        # TODO: Use httpx stream reading (client.stream + aiter_lines) to process
        # SearchStream batches as they arrive instead of buffering the full response.
        response = await http_request(
            "POST",
            url,
            headers=self._build_auth_headers(token, login_customer_id),
            json={"query": query},
            error_handler=_raise_google_error,
            retry_delay_parser=_extract_retry_delay,
        )
        return self._parse_stream(response.json())

    def _get_google_api_token(self, client_code: str) -> str:
        return _get_oauth_token() or fetch_google_api_token_simple(client_code)

    def _build_auth_headers(
        self, access_token: str, login_customer_id: str | None = None
    ) -> dict:
        if not self.developer_token or not access_token:
            raise GoogleAPIException(
                message="Missing Google Ads credentials",
                details={
                    "has_developer_token": bool(self.developer_token),
                    "has_access_token": bool(access_token),
                },
            )
        headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": self.developer_token,
            "Content-Type": "application/json",
        }
        if login_customer_id:
            headers["login-customer-id"] = login_customer_id
        return headers

    def _parse_stream(self, response_json) -> list:
        if isinstance(response_json, list):
            results = []
            for batch in response_json:
                results.extend(batch.get("results", []))
            return results
        logger.warning("SearchStream returned non-list response")
        return response_json.get("results", [])


def _get_oauth_token() -> str | None:
    global _cached_google_api_token, _google_api_token_expiry
    refresh_token = os.getenv("GOOGLE_ADS_REFRESH_TOKEN")
    if not refresh_token:
        return None

    if _cached_google_api_token and time.time() < _google_api_token_expiry:
        return _cached_google_api_token

    try:
        response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
            },
        )
        response.raise_for_status()
    except httpx.HTTPStatusError:
        error_body = response.text
        logger.error(
            "Local OAuth token refresh failed",
            component="google-auth",
            status=response.status_code,
            error=error_body,
        )
        raise GoogleAdsAuthException(
            message="Google OAuth token refresh failed. Check GOOGLE_ADS_REFRESH_TOKEN, CLIENT_ID, and CLIENT_SECRET in .env",
            details={"status": response.status_code, "error": error_body},
        )

    token_data = response.json()
    _cached_google_api_token = token_data["access_token"]
    _google_api_token_expiry = time.time() + token_data.get("expires_in", 3600) - 60
    logger.info("Google OAuth token refreshed", component="google-auth")

    return _cached_google_api_token


def _raise_google_error(response: httpx.Response) -> None:
    """Parse Google Ads API error response and raise structured exception."""
    error_message = f"Google Ads API failed: {response.status_code}"
    error_context = {"status_code": response.status_code}

    try:
        # Attempt to parse Google's structured error format
        error_payload = response.json().get("error", {})
        if error_payload:
            error_message = error_payload.get("message", error_message)

            # Extract specific errors if available (Google Ads Failure format)
            details_list = error_payload.get("details", [])
            if details_list and isinstance(details_list, list):
                # Usually the first detail contains the GoogleAdsFailure
                failure_info = details_list[0]
                error_context["errors"] = failure_info.get("errors", [])
                # Extract requestId for tracing
                if "requestId" in failure_info:
                    error_context["google_request_id"] = failure_info["requestId"]
    except Exception:
        # Fallback to raw text if JSON parsing fails
        error_context["response_text"] = response.text

    if response.status_code in (401, 403):
        raise GoogleAdsAuthException(
            message=f"Google Ads API authentication failed: {error_message}",
            details=error_context,
        )
    if response.status_code == 400:
        raise GoogleAdsValidationException(
            message=f"Google Ads API validation failed: {error_message}",
            details=error_context,
        )
    raise GoogleAPIException(
        message=f"{error_message}",
        details=error_context,
    )


def _extract_retry_delay(response: httpx.Response, default_delay: float) -> float:
    try:
        hint = (
            response.json()
            .get("error", {})
            .get("details", [{}])[0]
            .get("quotaErrorDetails", {})
            .get("retryDelay")
        )
        if hint:
            return int(hint.rstrip("s"))
    except (KeyError, ValueError, IndexError):
        pass
    return default_delay


# Singleton instance for shared use
google_ads_client = GoogleAdsClient()
