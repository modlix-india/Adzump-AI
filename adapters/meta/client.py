import os
from typing import Any

import httpx
import structlog

from adapters.meta.exceptions import MetaAPIError
from core.infrastructure.http_client import http_request
from oserver.services.connection import fetch_meta_api_token

META_BASE_URL = "https://graph.facebook.com/v22.0"

logger = structlog.get_logger(__name__)


class MetaClient:
    BASE_URL = META_BASE_URL

    async def post(
        self,
        endpoint: str,
        client_code: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = self._get_meta_api_token(client_code)
        url = f"{self.BASE_URL}{endpoint}"
        response = await http_request(
            "POST",
            url,
            json=json,
            params=params,
            headers=self._build_headers(token),
            error_handler=_handle_meta_error,
        )
        return response.json()

    async def get(
        self,
        endpoint: str,
        client_code: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = self._get_meta_api_token(client_code)
        url = f"{self.BASE_URL}{endpoint}"
        response = await http_request(
            "GET",
            url,
            params=params,
            headers=self._build_headers(token),
            error_handler=_handle_meta_error,
        )
        return response.json()

    def _get_meta_api_token(self, client_code: str) -> str:
        env_token = os.getenv("META_ACCESS_TOKEN")
        if env_token:
            return env_token
        return fetch_meta_api_token(client_code)

    def _build_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }


def _handle_meta_error(response: httpx.Response) -> None:
    error_data = response.json()
    logger.error("Meta API error", status=response.status_code, error=error_data)
    error_msg = error_data.get("error", {}).get("message", "Unknown error")
    raise MetaAPIError(error_msg, response.status_code, error_data)


meta_client = MetaClient()
