from typing import Any, Optional

import httpx
import structlog

from adapters.meta.exceptions import MetaAPIError
from core.infrastructure.http_client import http_request

META_BASE_URL = "https://graph.facebook.com/v22.0"

logger = structlog.get_logger()


class MetaClient:
    def __init__(self, access_token: str):
        self.access_token = access_token

    async def post(
        self,
        endpoint: str,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        url = f"{META_BASE_URL}{endpoint}"
        response = await http_request(
            "POST",
            url,
            json=json,
            params=params,
            headers=self._headers(),
            error_handler=_handle_meta_error,
        )
        return response.json()

    async def get(
        self,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        url = f"{META_BASE_URL}{endpoint}"
        response = await http_request(
            "GET",
            url,
            params=params,
            headers=self._headers(),
            error_handler=_handle_meta_error,
        )
        return response.json()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }


def _handle_meta_error(response: httpx.Response) -> None:
    error_data = response.json()
    logger.error("Meta API error", status=response.status_code, error=error_data)
    error_msg = error_data.get("error", {}).get("message", "Unknown error")
    raise MetaAPIError(error_msg, response.status_code, error_data)
