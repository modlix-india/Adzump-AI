from typing import Optional
from structlog import get_logger  # type: ignore

from oserver.services.storage_service import StorageService
from oserver.services.file_service import StorageFileService
from oserver.models.storage_request_model import (
    StorageFilter,
    StorageReadRequest,
    StorageUpdateWithPayload,
    StorageRequestWithPayload,
)
from oserver.utils.helpers import generate_filename_from_url
from utils.helpers import normalize_url

logger = get_logger(__name__)


class ScreenshotStorageHandler:
    STORAGE_NAME = "AISuggestedData"
    APP_CODE = "marketingai"

    def __init__(
        self,
        access_token: str,
        client_code: str,
        x_forwarded_host: Optional[str] = None,
        x_forwarded_port: Optional[str] = None,
    ):
        self.client_code = client_code

        self.storage = StorageService(
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port,
        )

        self.file_storage = StorageFileService(
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port,
        )

    async def get_record(
        self, business_url: str
    ) -> tuple[Optional[dict], Optional[str]]:
        business_url = normalize_url(business_url)
        read_req = StorageReadRequest(
            storageName=self.STORAGE_NAME,
            appCode=self.APP_CODE,
            clientCode=self.client_code,
            filter=StorageFilter(field="businessUrl", value=business_url),
        )

        response = await self.storage.read_page_storage(read_req)

        if not response.success:
            return None, None

        try:
            content = (
                response.result[0]
                .get("result", {})
                .get("result", {})
                .get("content", [])
            )

            if content:
                record = content[0]
                storage_id = record.get("_id")
                return record, storage_id
        except (IndexError, KeyError, TypeError):
            pass

        return None, None

    async def get_cached_screenshot(
        self,
        business_url: str,
        url: str,
    ) -> Optional[str]:
        url = normalize_url(url)
        business_url = normalize_url(business_url)

        record, _ = await self.get_record(business_url)
        if not record:
            return None

        is_external = url != business_url

        if not is_external:
            return record.get("screenshot")

        # Check external links
        for link in record.get("externalLinks", []):
            if normalize_url(link.get("url")) == url:
                return link.get("screenshot")

        return None

    async def upload_screenshot(
        self,
        screenshot_bytes: bytes,
        url: str,
    ) -> str:
        upload = await self.file_storage.upload_file(
            image_bytes=screenshot_bytes,
            filename=generate_filename_from_url(url),
            folder_name="screenshots",
        )

        if not upload.success:
            logger.error(
                "[ScreenshotStorageHandler] Upload failed",
                url=url,
                result=upload.result,
            )
            raise RuntimeError(f"Screenshot upload failed: {upload.result}")

        return upload.result.get("url")

    async def save_screenshot(
        self,
        business_url: str,
        url: str,
        screenshot_url: str,
    ) -> str:
        business_url = normalize_url(business_url)
        url = normalize_url(url)
        is_external = url != business_url

        record, storage_id = await self.get_record(business_url)

        # Create new record if none exists
        if not record:
            return await self._create_record(business_url, screenshot_url)

        # Update existing record
        if not is_external:
            await self._update_business_screenshot(storage_id, screenshot_url)
        else:
            await self._update_external_screenshot(
                storage_id, record, url, screenshot_url
            )

        return storage_id

    async def _create_record(
        self,
        business_url: str,
        screenshot_url: str,
    ) -> str:
        """Create new storage record."""
        req = StorageRequestWithPayload(
            storageName=self.STORAGE_NAME,
            clientCode=self.client_code,
            appCode=self.APP_CODE,
            dataObject={
                "businessUrl": business_url,
                "screenshot": screenshot_url,
                "externalLinks": [],
            },
        )

        response = await self.storage.write_storage(req)

        if response.success:
            return response.result[0]["result"]["result"]["_id"]

        raise RuntimeError("Failed to create storage record")

    async def _update_business_screenshot(
        self,
        storage_id: str,
        screenshot_url: str,
    ) -> None:
        """Update main business screenshot."""
        update = StorageUpdateWithPayload(
            storageName=self.STORAGE_NAME,
            clientCode=self.client_code,
            appCode=self.APP_CODE,
            dataObjectId=storage_id,
            dataObject={"screenshot": screenshot_url},
        )
        await self.storage.update_storage(update)

    async def _update_external_screenshot(
        self,
        storage_id: str,
        record: dict,
        url: str,
        screenshot_url: str,
    ) -> None:
        """Update or add external link screenshot."""
        links = record.get("externalLinks", [])
        updated = False

        for link in links:
            if normalize_url(link.get("url")) == url:
                link["screenshot"] = screenshot_url
                updated = True
                break

        if not updated:
            links.append({"url": url, "screenshot": screenshot_url})

        update = StorageUpdateWithPayload(
            storageName=self.STORAGE_NAME,
            clientCode=self.client_code,
            appCode=self.APP_CODE,
            dataObjectId=storage_id,
            dataObject={"externalLinks": links},
        )
        await self.storage.update_storage(update)
