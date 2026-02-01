from typing import Any, Optional

import httpx
import structlog

META_BASE_URL = "https://graph.facebook.com/v22.0"
META_HTTP_TIMEOUT = 30

logger = structlog.get_logger()

# Module-level client - reused across all requests for connection pooling
_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            base_url=META_BASE_URL,
            timeout=META_HTTP_TIMEOUT,
        )
    return _http_client


class MetaClient:
    def __init__(self, access_token: str):
        self.access_token = access_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def post(
        self,
        endpoint: str,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        client = _get_http_client()
        response = await client.post(
            endpoint, json=json, params=params, headers=self._headers()
        )
        return self._handle_response(response)

    async def get(
        self,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        client = _get_http_client()
        response = await client.get(endpoint, params=params, headers=self._headers())
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        from adapters.meta.exceptions import MetaAPIError

        if response.status_code != 200:
            error_data = response.json()
            logger.error(
                "Meta API error", status=response.status_code, error=error_data
            )
            error_msg = error_data.get("error", {}).get("message", "Unknown error")
            raise MetaAPIError(error_msg, response.status_code, error_data)

        return response.json()
