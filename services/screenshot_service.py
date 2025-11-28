from playwright.async_api import async_playwright
from oserver.utils.helpers import generate_filename_from_url
from oserver.services.file_service import StorageFileService


async def take_and_upload_screenshot(url, access_token, client_code, xh, xp):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="load", timeout=60000)
        await page.wait_for_timeout(2000)
        screenshot_bytes = await page.screenshot(full_page=True)
        await browser.close()

    file_service = StorageFileService(
        access_token=access_token,
        client_code=client_code,
        x_forwarded_host=xh,
        x_forwarded_port=xp
    )

    resp = await file_service.upload_file(screenshot_bytes, generate_filename_from_url(url), "screenshots")

    if not resp.success:
        raise Exception("Failed to upload screenshot")

    return resp.result.get("url")
