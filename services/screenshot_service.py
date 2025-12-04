import logging
from typing import Optional
from fastapi import HTTPException
from playwright.async_api import async_playwright
from exceptions.custom_exceptions import BusinessValidationException
from models.business_model import ScreenshotResponse
from oserver.utils.helpers import generate_filename_from_url
from utils.helpers import normalize_url
from oserver.services.storage_service import StorageService
from oserver.services.file_service import StorageFileService
from oserver.models.storage_request_model import (
    StorageFilter,
    StorageReadRequest,
    StorageUpdateWithPayload,
    StorageRequestWithPayload
)

logger = logging.getLogger(__name__)


class ScreenshotService:

    def __init__(self, access_token: str, client_code: str, xh: Optional[str], xp: Optional[str]):
        self.access_token = access_token
        self.client_code = client_code
        self.xh = xh
        self.xp = xp

        self.storage = StorageService(
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=xh,
            x_forwarded_port=xp
        )

        self.file_storage = StorageFileService(
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=xh,
            x_forwarded_port=xp
        )

        logger.info("[ScreenshotService] Initialized")

    # INTERNAL: Take + Upload
    async def _take_and_upload_screenshot(self, url: str) -> str:
        logger.info(f"[ScreenshotService] Taking screenshot → {url}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            logger.info("[ScreenshotService] Navigating page...")
            await page.goto(url, wait_until="load", timeout=60000)
            await page.wait_for_timeout(2000)

            logger.info("[ScreenshotService] Capturing screenshot...")
            screenshot_bytes = await page.screenshot(full_page=True)
            await browser.close()

        logger.info("[ScreenshotService] Uploading screenshot to storage...")

        upload = await self.file_storage.upload_file(
            image_bytes=screenshot_bytes,
            filename=generate_filename_from_url(url),
            folder_name="screenshots"
        )

        if not upload.success:
            logger.error("[ScreenshotService] Upload failed")
            raise HTTPException(500, "Screenshot upload failed")

        logger.info("[ScreenshotService] Screenshot uploaded successfully")
        return upload.result.get("url")

    # MAIN PROCESS FLOW
    async def process(self, business_url: str, url: str, retake: bool) -> ScreenshotResponse:
        business_url = normalize_url(business_url)
        url = normalize_url(url)

        is_external = (url != business_url)

        logger.info(f"[ScreenshotService] Process Start | business={business_url}, url={url}, retake={retake}, external={is_external}")

        # 1. Read storage record
        logger.info("[ScreenshotService] Reading AISuggestedData record...")
        read_req = StorageReadRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            clientCode=self.client_code,
            filter=StorageFilter(field="businessUrl", value=business_url)
        )

        read_res = await self.storage.read_page_storage(read_req)
        content = read_res.result[0].get("result", {}).get("result", {}).get("content", []) if read_res.success else []
        record = content[0] if content else None
        storage_id = record["_id"] if record else None

        logger.info(f"[ScreenshotService] Storage record found: {bool(record)} | storageId={storage_id}")

        # 2. External screenshot requires existing record
        if is_external and not record:
            logger.warning("[ScreenshotService] External URL with no parent record → invalid")
            raise BusinessValidationException("External screenshot requires existing business record")

        # 3. Check existing screenshot
        existing_screenshot = None

        if not is_external:
            existing_screenshot = record.get("screenshot") if record else None
        else:
            for l in record.get("externalLinks", []):
                if normalize_url(l.get("url")) == url:
                    existing_screenshot = l.get("screenshot")
                    break

        logger.info(f"[ScreenshotService] Existing screenshot found: {bool(existing_screenshot)}")

        # 4. Cached path
        if existing_screenshot and not retake:
            logger.info("[ScreenshotService] Returning cached screenshot")
            return ScreenshotResponse(
                url=url,
                storage_id=storage_id,
                screenshot=existing_screenshot
            )

        # 5. New screenshot required
        logger.info("[ScreenshotService] Capture new screenshot required")
        screenshot_url = await self._take_and_upload_screenshot(url)

        # 6. Create new record if none exists
        if not record:
            logger.info("[ScreenshotService] Creating new AISuggestedData record...")
            req = StorageRequestWithPayload(
                storageName="AISuggestedData",
                clientCode=self.client_code,
                appCode="marketingai",
                dataObject={
                    "businessUrl": business_url,
                    "screenshot": screenshot_url,
                    "externalLinks": []
                }
            )
            create_response = await self.storage.write_storage(req)
            storage_id = None
            logger.info(f"[ScreenshotService] New record created with ID: {create_response.result[0]["result"]["result"]["_id"]}")
            if create_response.success:
                storage_id = create_response.result[0]["result"]["result"]["_id"]
            return ScreenshotResponse(
                url=url,
                screenshot=screenshot_url,
                storage_id=storage_id
            )
        # 7. Update existing record
        if not is_external:
            logger.info("[ScreenshotService] Updating business screenshot...")
            update = StorageUpdateWithPayload(
                storageName="AISuggestedData",
                clientCode=self.client_code,
                appCode="marketingai",
                dataObjectId=storage_id,
                dataObject={"screenshot": screenshot_url}
            )
            await self.storage.update_storage(update)
        else:
            logger.info("[ScreenshotService] Updating external link screenshot...")
            links = record.get("externalLinks", [])
            updated = False

            for l in links:
                if normalize_url(l["url"]) == url:
                    l["screenshot"] = screenshot_url
                    updated = True
                    break

            if not updated:
                links.append({"url": url, "screenshot": screenshot_url})

            update = StorageUpdateWithPayload(
                storageName="AISuggestedData",
                clientCode=self.client_code,
                appCode="marketingai",
                dataObjectId=storage_id,
                dataObject={"externalLinks": links}
            )
            await self.storage.update_storage(update)

        logger.info("[ScreenshotService] Screenshot flow completed successfully")
        return ScreenshotResponse(
            url=url,
            storage_id=storage_id,
            screenshot=screenshot_url
        )
