from typing import Optional
import httpx
from oserver.models.storage_request_model import (
    StorageRequest,
    StorageRequestWithPayload,
    StorageReadRequest,
    StorageUpdateWithPayload,
)
from oserver.models.storage_response_model import StorageResponse
from oserver.services.base_api_service import BaseAPIService
from core.context import auth_context


class StorageService:
    """Storage service that reads auth from context lazily if not provided explicitly."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        client_code: Optional[str] = None,
        x_forwarded_host: Optional[str] = None,
        x_forwarded_port: Optional[str] = None,
    ):
        self._access_token = access_token
        self._client_code = client_code
        self.x_forwarded_host = x_forwarded_host
        self.x_forwarded_port = x_forwarded_port
        self.client = BaseAPIService()

    @property
    def access_token(self) -> str:
        return self._access_token or auth_context.access_token

    @property
    def client_code(self) -> str:
        return self._client_code or auth_context.client_code

    def _headers(self):
        return {
            "authorization": self.access_token,
            "content-type": "application/json",
            "clientCode": self.client_code,
            "X-Forwarded-Host": self.x_forwarded_host or "",
            "X-Forwarded-Port": self.x_forwarded_port or "",
        }

    async def read_storage(self, request: StorageRequest) -> StorageResponse:
        url = f"{self.client.base_url}/api/core/function/execute/CoreServices.Storage/Read"
        try:
            result = await self.client.request("POST", url, headers=self._headers(), payload=request.model_dump())
            return StorageResponse(success=True, result=result)
        except httpx.RequestError as e:
            return StorageResponse(success=False, error=f"Network error: {str(e)}")
        except Exception as e:
            return StorageResponse(success=False, error=f"Unexpected error: {str(e)}")

    async def read_page_storage(self, request: StorageReadRequest) -> StorageResponse:
        url = f"{self.client.base_url}/api/core/function/execute/CoreServices.Storage/ReadPage"
        try:
            result = await self.client.request("POST", url, headers=self._headers(), payload=request.model_dump())
            return StorageResponse(success=True, result=result)
        except httpx.RequestError as e:
            return StorageResponse(success=False, error=f"Network error: {str(e)}")
        except Exception as e:
            return StorageResponse(success=False, error=f"Unexpected error: {str(e)}")

    async def write_storage(self, request: StorageRequestWithPayload) -> StorageResponse:
        url = f"{self.client.base_url}/api/core/function/execute/CoreServices.Storage/Create"
        try:
            result = await self.client.request("POST", url, headers=self._headers(), payload=request.model_dump())
            return StorageResponse(success=True, result=result)
        except httpx.RequestError as e:
            return StorageResponse(success=False, error=f"Network error: {str(e)}")
        except Exception as e:
            return StorageResponse(success=False, error=f"Unexpected error: {str(e)}")
    
    async def update_storage(self, request: StorageUpdateWithPayload) -> StorageResponse:
        url = f"{self.client.base_url}/api/core/function/execute/CoreServices.Storage/Update"
        try:
            result = await self.client.request("POST", url, headers=self._headers(), payload=request.model_dump())
            return StorageResponse(success=True, result=result)
        except httpx.RequestError as e:
            return StorageResponse(success=False, error=f"Network error: {str(e)}")
        except Exception as e:
            return StorageResponse(success=False, error=f"Unexpected error: {str(e)}")
