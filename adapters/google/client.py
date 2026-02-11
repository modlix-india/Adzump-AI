import os

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


class GoogleAdsClient:
    BASE_URL = "https://googleads.googleapis.com"
    API_VERSION = "v21"

    def __init__(self) -> None:
        self.developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")

    async def get(self, endpoint: str, client_code: str) -> dict:
        """Execute a GET request against the Google Ads REST API."""
        token = self._get_token(client_code)
        url = f"{self.BASE_URL}/{self.API_VERSION}/{endpoint}"
        response = await http_request(
            "GET",
            url,
            headers=self._headers(token),
            error_handler=_handle_google_error,
        )
        return response.json()

    async def search_stream(
        self, query: str, customer_id: str, login_customer_id: str, client_code: str
    ) -> list:
        """Execute GAQL query via searchStream."""
        token = self._get_token(client_code)
        url = f"{self.BASE_URL}/{self.API_VERSION}/customers/{customer_id}/googleAds:searchStream"

        # TODO: Use httpx stream reading (client.stream + aiter_lines) to process
        # SearchStream batches as they arrive instead of buffering the full response.
        response = await http_request(
            "POST",
            url,
            headers=self._headers(token, login_customer_id),
            json={"query": query},
            error_handler=_handle_google_error,
            retry_delay_parser=_parse_google_retry_delay,
        )
        return self._parse_stream(response.json())

    def _get_token(self, client_code: str) -> str:
        return os.getenv("GOOGLE_ADS_ACCESS_TOKEN") or fetch_google_api_token_simple(
            client_code
        )

    def _headers(self, access_token: str, login_customer_id: str | None = None) -> dict:
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


def _handle_google_error(response: httpx.Response) -> None:
    if response.status_code in (401, 403):
        raise GoogleAdsAuthException(
            message=f"Google Ads API authentication failed ({response.status_code})",
            details={"response": response.text},
        )
    if response.status_code == 400:
        raise GoogleAdsValidationException(
            message="Google Ads API validation failed (400)",
            details={"response": response.text},
        )
    raise GoogleAPIException(
        message=f"Google Ads API failed: {response.text}",
        details={"status_code": response.status_code},
    )


def _parse_google_retry_delay(response: httpx.Response, default_delay: float) -> float:
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
