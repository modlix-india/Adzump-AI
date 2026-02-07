import os
from oserver.services.connection import fetch_google_api_token_simple
from core.infrastructure.http_client import get_http_client
from exceptions.custom_exceptions import GoogleAPIException


class GoogleAdsClient:
    BASE_URL = "https://googleads.googleapis.com"
    API_VERSION = "v21"

    def __init__(self) -> None:
        self.developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")

    async def get(self, endpoint: str, client_code: str) -> dict:
        """Authenticated GET request to Google Ads API."""
        token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN") or fetch_google_api_token_simple(client_code)
        headers = self._headers(token)
        url = f"{self.BASE_URL}/{self.API_VERSION}/{endpoint}"

        http = get_http_client()
        response = await http.get(url, headers=headers)

        if response.status_code != 200:
            raise GoogleAPIException(
                message=f"Google Ads API failed: {response.text}",
                details={"status_code": response.status_code},
            )

        return response.json()

    async def search_stream(
        self, query: str, customer_id: str, login_customer_id: str, client_code: str
    ) -> list:
        """Execute GAQL query via searchStream."""
        token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN") or fetch_google_api_token_simple(client_code)
        headers = self._headers(token, login_customer_id)
        url = f"{self.BASE_URL}/{self.API_VERSION}/customers/{customer_id}/googleAds:searchStream"

        http = get_http_client()
        # TODO: Use httpx stream reading (client.stream + aiter_lines) to process
        # SearchStream batches as they arrive instead of buffering the full response.
        response = await http.post(url, headers=headers, json={"query": query})

        if response.status_code != 200:
            raise GoogleAPIException(
                message=f"Google Ads API failed: {response.text}",
                details={"status_code": response.status_code},
            )

        try:
            return self._parse_stream(response.json())
        except Exception as e:
            raise GoogleAPIException(message=f"Failed to parse response: {e}")

    def _headers(self, access_token: str, login_customer_id: str | None = None) -> dict:
        """Build common headers for Google Ads API requests."""
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

    def _parse_stream(self, response_json: list) -> list:
        """Parse streaming response into flat results list."""
        results = []
        for chunk in response_json:
            results.extend(chunk.get("results", []))
        return results
