from typing import Optional
import httpx
from oserver.services.base_api_service import BaseAPIService
from oserver.models.storage_response_model import StorageResponse
import logging

logger = logging.getLogger(__name__)


class StorageFileService:
    def __init__(
        self,
        access_token: str,
        client_code: str,
        x_forwarded_host: Optional[str] = None,
        x_forwarded_port: Optional[str] = None,
    ):
        self.access_token = access_token
        self.client_code = client_code
        self.x_forwarded_host = x_forwarded_host
        self.x_forwarded_port = x_forwarded_port
        self.app_code = "marketingai"
        self.client = BaseAPIService()

    def _headers(self):
        return {
            "accept": "application/json",
            "Authorization": self.access_token,
            "ClientCode": self.client_code,
            "AppCode": self.app_code,
            "X-Forwarded-Host": self.x_forwarded_host or "",
            "X-Forwarded-Port": self.x_forwarded_port or "",
        }

    async def create_folder(self, folder_name: str) -> StorageResponse:
        url = f"{self.client.base_url}/api/files/secured/directory/{folder_name}"
        try:
            result = await self.client.request("POST", url, headers=self._headers())
            return StorageResponse(success=True, result=result)
        except Exception as e:
            return StorageResponse(success=False, error=str(e))

    async def get_folder(self, folder_name: str) -> StorageResponse:
        url = f"{self.client.base_url}/api/files/secured/{folder_name}"
        headers= self._headers()
        headers["x-debug"] = "kailash123"

        logger.info(f"Request URL: {url}")
        logger.info(f"Request Headers: {headers}")

        try:
            result = await self.client.request("GET", url, headers=headers)
            
            return StorageResponse(success=True, result=result)
        except Exception as e:
            return StorageResponse(success=False, error=str(e))

    async def ensure_folder(self, folder_name: str) -> bool:
        get_resp = await self.get_folder(folder_name)
        if get_resp.success:
            return True

        create_resp = await self.create_folder(folder_name)
        return create_resp.success

    async def upload_file(self, image_bytes: bytes, filename: str, folder_name: str) -> StorageResponse:
        try:
            await self.ensure_folder(folder_name)
            url = f"{self.client.base_url}/api/files/secured/{folder_name}?clientCode={self.client_code}"
            files = {"file": (filename, image_bytes, "image/png")}
            result = await self.client.request("POST", url, headers=self._headers(), files=files)
            return StorageResponse(success=True, result=result)
        except httpx.RequestError as e:
            return StorageResponse(success=False, error=f"Network error: {str(e)}")
        except Exception as e:
            return StorageResponse(success=False, error=f"Unexpected error: {str(e)}")
