import logging
import json
from typing import List
from exceptions.custom_exceptions import (
    AIProcessingException,
    BusinessValidationException,
)
from services.scraper_service import scrape_website
from services.screenshot_service import take_and_upload_screenshot
from utils import prompt_loader
from models.business_model import BusinessMetadata
from fastapi import HTTPException
from oserver.models.storage_request_model import (
    StorageFilter,
    StorageReadRequest,
    StorageRequest,
    StorageRequestWithPayload,
    StorageUpdateWithPayload,
)
from services.openai_client import chat_completion
from oserver.services.storage_service import StorageService
from utils.helpers import normalize_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BusinessService:
    OPENAI_MODEL = "gpt-4o-mini"

    async def extract_business_metadata(
        self, scraped_data: str, url: str = None
    ) -> BusinessMetadata:
        prompt = prompt_loader.format_prompt(
            "business_metadata_prompt.txt", scraped_data=scraped_data, url=url
        )
        try:
            resp = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.OPENAI_MODEL,
                max_tokens=500,
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            raw = resp.choices[0].message.content.strip()
            data = json.loads(raw)

            brand_info = BusinessMetadata.from_raw_data(data)
            logger.info(f"Extracted brand info: {brand_info.model_dump()}")
            return brand_info

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parsing failed: {e}, using defaults")
            return BusinessMetadata()
        except Exception as e:
            logger.warning(f"Brand extraction failed: {e}, using defaults")
            return BusinessMetadata()

    async def extract_business_unique_features(self, scraped_data: str) -> List[str]:
        prompt = prompt_loader.format_prompt(
            "business_usp_prompt.txt", scraped_data=scraped_data
        )

        try:
            resp = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.OPENAI_MODEL,
                max_tokens=400,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            usp_data = json.loads(resp.choices[0].message.content.strip())
            unique_features = usp_data.get("features", [])

            logger.info(f"Extracted and validated USPs: {unique_features}")
            return unique_features

        except Exception as e:
            logger.warning(f"USP extraction failed: {e}")
            return []

    @staticmethod
    async def fetch_product_details(
        data_object_id: str,
        access_token: str,
        client_code: str,
        x_forwarded_host: str,
        x_forwarded_port: str,
    ):
        payload = StorageRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            dataObjectId=data_object_id,
            eager=False,
            eagerFields=[],
        )
        storage_service = StorageService(
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port,
        )
        response = await storage_service.read_storage(payload)
        if not response.success or not response.result:
            raise HTTPException(
                status_code=500,
                detail=response.error or "Failed to fetch product details",
            )
        data = response.result
        try:
            if isinstance(data, list) and len(data) > 0:
                product_data = data[0]["result"]["result"]
            elif isinstance(data, dict) and "result" in data:
                product_data = data["result"]["result"]
            else:
                raise HTTPException(
                    status_code=500, detail="Unexpected product data format"
                )
        except (KeyError, IndexError, TypeError):
            raise HTTPException(
                status_code=500, detail="Invalid product data response structure"
            )
        return product_data


async def process_website_data(
    website_url: str,
    access_token: str,
    client_code: str,
    x_forwarded_host: str,
    x_forwarded_port: str,
    rescrape: bool = False,
):
    try:
        logger.info(f"Checking if {website_url} already exists in storage")

        # Normalize incoming URL
        website_url = normalize_url(website_url)
        logger.info(f"Normalized URL: {website_url}")

        storage_service = StorageService(
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port,
        )
        # STEP 1: READ EXISTING RECORD
        read_request = StorageReadRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            clientCode=client_code,
            filter=StorageFilter(field="businessUrl", value=website_url),
        )
        existing_data_response = await storage_service.read_page_storage(read_request)
        logger.info(f"Storage read response: {existing_data_response}")

        existing_record = None
        existing_id = None
        existing_summary = None
        existing_businessType = None
        existing_finalSummary = None

        if existing_data_response.success:
            try:
                records = (
                    existing_data_response.result[0]
                    .get("result", {})
                    .get("result", {})
                    .get("content", [])
                )

                if records:
                    existing_record = records[-1]
                    existing_id = existing_record.get("_id")
                    existing_businessType = existing_record.get("businessType", "")
                    existing_summary = existing_record.get("summary", "")
                    existing_finalSummary = existing_record.get("finalSummary", "")
            except Exception as e:
                logger.warning(f"Error parsing existing storage data: {e}")

        # STEP 2: DEFAULT BEHAVIOR IF SUMMARY EXISTS & rescrape=False
        if (
            existing_id
            and existing_summary
            and existing_summary.strip()
            and not rescrape
        ):
            logger.info(f"Returning cached summary for {website_url}")

            return {
                "websiteUrl": website_url,
                "summary": existing_summary,
                "businessType": existing_businessType,
                "finalSummary": existing_finalSummary,
                "storageId": existing_id,
            }

        # STEP 3: SCRAPE WEBSITE
        logger.info(f"Scraping website: {website_url}")
        scraped_data = await scrape_website(website_url)

        if not scraped_data:
            raise HTTPException(status_code=500, detail="Failed to scrape website")

        # STEP 4: GENERATE SUMMARY USING LLM
        logger.info(f"Generating summary for {website_url}")
        summary_raw = await generate_website_summary(scraped_data)

        try:
            parsed = json.loads(summary_raw)
        except:
            parsed = json.loads(summary_raw.replace("'", '"'))

        summary_text = parsed.get("summary", "")
        businessType = parsed.get("businessType", "")

        # STEP 5: DECIDE UPDATE OR CREATE
        # Case A: UPDATE EXISTING RECORD
        if existing_id:
            logger.info(f"Updating existing record: {existing_id}")

            update_payload = StorageUpdateWithPayload(
                storageName="AISuggestedData",
                clientCode=client_code,
                appCode="",
                dataObjectId=existing_id,
                dataObject={
                    "summary": summary_text,
                    "businessType": businessType,
                    "finalSummary": summary_text,
                    "siteLinks": scraped_data.get("links", []),
                },
            )

            response = await storage_service.update_storage(update_payload)
            logger.info(f"Update response: {response}")
            return {
                "websiteUrl": website_url,
                "summary": summary_text,
                "businessType": businessType,
                "finalSummary": summary_text,
                "storageId": existing_id,
            }

        # Case B: CREATE NEW RECORD
        logger.info("No existing record found → creating new")

        create_payload = StorageRequestWithPayload(
            storageName="AISuggestedData",
            clientCode=client_code,
            appCode="",
            dataObject={
                "businessUrl": website_url,
                "summary": summary_text,
                "businessType": businessType,
                "finalSummary": summary_text,
                "siteLinks": scraped_data.get("links", []),
            },
        )

        create_response = await storage_service.write_storage(create_payload)

        # Extract _id from NCLC response structure
        new_storage_id = None
        result_block = create_response.result

        if isinstance(result_block, dict):
            new_storage_id = result_block.get("dataObjectId") or result_block.get(
                "result", {}
            ).get("result", {}).get("_id")

        elif isinstance(result_block, list) and len(result_block) > 0:
            item = result_block[0]
            if "dataObjectId" in item:
                new_storage_id = item["dataObjectId"]
            elif (
                isinstance(item, dict)
                and "result" in item
                and isinstance(item["result"], dict)
                and "result" in item["result"]
            ):
                new_storage_id = item["result"]["result"].get("_id")

        logger.info(f"Extracted Storage ID: {new_storage_id}")

        return {
            "websiteUrl": website_url,
            "summary": summary_text,
            "businessType": businessType,
            "finalSummary": summary_text,
            "storageId": new_storage_id,
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(f"Unexpected error in process_website_data: {e}")
        raise HTTPException(
            status_code=500, detail="Internal server error during website processing"
        )


async def generate_website_summary(scraped_data: dict) -> str:
    if not scraped_data:
        raise BusinessValidationException(
            "Scraped data is required for summary generation"
        )

    try:
        prompt = prompt_loader.format_prompt(
            "website_summary_prompt.txt", scraped_data=scraped_data
        )
        response = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            max_tokens=500,
            temperature=0.2,
        )
        logger.info("Summary generated successfully")
        logger.debug(f"Summary response: {response}")
        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        raise AIProcessingException("Failed to generate summary")


async def process_screenshot_flow(
    business_url: str,
    retake: bool,
    access_token: str,
    client_code: str,
    x_forwarded_host: str,
    x_forwarded_port: str,
    external_url: str | None = None,
):
    business_url = normalize_url(business_url)
    external_url = normalize_url(external_url) if external_url else None

    logger.info(
        f"[ScreenshotFlow] Started businessUrl={business_url}, externalUrl={external_url}, retake={retake}"
    )

    storage_service = StorageService(
        access_token=access_token,
        client_code=client_code,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port,
    )

    # READ EXISTING RECORD
    read_request = StorageReadRequest(
        storageName="AISuggestedData",
        appCode="marketingai",
        clientCode=client_code,
        filter=StorageFilter(field="businessUrl", value=business_url),
    )
    read_response = await storage_service.read_page_storage(read_request)

    existing_record = None
    if read_response.success and read_response.result:
        items = (
            read_response.result[0]
            .get("result", {})
            .get("result", {})
            .get("content", [])
        )
        if items:
            existing_record = items[0]

    record_exists = existing_record is not None
    storage_record_id = existing_record["_id"] if record_exists else None

    logger.info(f"[ScreenshotFlow] Existing Record ID = {storage_record_id}")

    # EXTERNAL LINK SCREENSHOT FLOW
    if external_url:
        if not record_exists:
            raise BusinessValidationException(
                "No record found for this businessUrl. Cannot process externalUrl screenshot."
            )
        logger.info("[ScreenshotFlow] External URL screenshot flow")

        # Load existing external links
        external_links_list = existing_record.get("externalLinks", [])

        # Deduplicate by normalized URL (keep latest entry)
        normalized_map = {}
        for entry in external_links_list:
            key = normalize_url(entry.get("url", ""))
            normalized_map[key] = entry

        external_links_list = list(normalized_map.values())
        existing_external_item = normalized_map.get(external_url)

        screenshot_missing = (
            not existing_external_item or not existing_external_item.get("screenshot")
        )

        # retake = TRUE
        if retake:
            screenshot_url = await take_and_upload_screenshot(
                external_url,
                access_token,
                client_code,
                x_forwarded_host,
                x_forwarded_port,
            )

            if existing_external_item:
                existing_external_item["screenshot"] = screenshot_url
            else:
                external_links_list.append(
                    {"url": external_url, "screenshot": screenshot_url}
                )

            update_request = StorageUpdateWithPayload(
                storageName="AISuggestedData",
                clientCode=client_code,
                appCode="marketingai",
                dataObjectId=storage_record_id,
                dataObject={"externalLinks": external_links_list},
            )

            await storage_service.update_storage(update_request)

            return {
                "businessUrl": business_url,
                "externalUrl": external_url,
                "externalScreenshotUrl": screenshot_url,
                "storageId": storage_record_id,
            }

        # retake = FALSE + screenshot EXISTS → return cached
        if existing_external_item and not screenshot_missing:
            return {
                "businessUrl": business_url,
                "externalUrl": external_url,
                "externalScreenshotUrl": existing_external_item["screenshot"],
                "storageId": storage_record_id,
            }

        # retake = FALSE + screenshot missing → take screenshot
        screenshot_url = await take_and_upload_screenshot(
            external_url, access_token, client_code, x_forwarded_host, x_forwarded_port
        )

        if existing_external_item:
            existing_external_item["screenshot"] = screenshot_url
        else:
            external_links_list.append(
                {"url": external_url, "screenshot": screenshot_url}
            )

        update_request = StorageUpdateWithPayload(
            storageName="AISuggestedData",
            clientCode=client_code,
            appCode="marketingai",
            dataObjectId=storage_record_id,
            dataObject={"externalLinks": external_links_list},
        )
        await storage_service.update_storage(update_request)

        return {
            "businessUrl": business_url,
            "externalUrl": external_url,
            "externalScreenshotUrl": screenshot_url,
            "storageId": storage_record_id,
        }

    # MAIN BUSINESS URL SCREENSHOT FLOW (NO external_url)
    logger.info("[ScreenshotFlow] Main business URL screenshot flow")

    screenshot_missing = not record_exists or not existing_record.get("screenshot")

    # No retake + screenshot exists → return cached
    if not retake and record_exists and not screenshot_missing:
        return {
            "businessUrl": business_url,
            "businessScreenshotUrl": existing_record["screenshot"],
            "storageId": storage_record_id,
        }

    # No retake + record exists + screenshot missing → take screenshot
    if not retake and record_exists and screenshot_missing:
        screenshot_url = await take_and_upload_screenshot(
            business_url, access_token, client_code, x_forwarded_host, x_forwarded_port
        )

        update_request = StorageUpdateWithPayload(
            storageName="AISuggestedData",
            clientCode=client_code,
            appCode="marketingai",
            dataObjectId=storage_record_id,
            dataObject={"screenshot": screenshot_url},
        )
        await storage_service.update_storage(update_request)

        return {
            "businessUrl": business_url,
            "businessScreenshotUrl": screenshot_url,
            "storageId": storage_record_id,
        }

    # No record → create one
    if not record_exists:
        screenshot_url = await take_and_upload_screenshot(
            business_url, access_token, client_code, x_forwarded_host, x_forwarded_port
        )

        create_request = StorageRequestWithPayload(
            storageName="AISuggestedData",
            clientCode=client_code,
            appCode="marketingai",
            dataObject={
                "businessUrl": business_url,
                "screenshot": screenshot_url,
                "externalLinks": [],
            },
        )
        await storage_service.write_storage(create_request)

        return {"businessUrl": business_url, "businessScreenshotUrl": screenshot_url}

    # retake=True + record exists
    screenshot_url = await take_and_upload_screenshot(
        business_url, access_token, client_code, x_forwarded_host, x_forwarded_port
    )

    update_request = StorageUpdateWithPayload(
        storageName="AISuggestedData",
        clientCode=client_code,
        appCode="marketingai",
        dataObjectId=storage_record_id,
        dataObject={"screenshot": screenshot_url},
    )
    await storage_service.update_storage(update_request)

    return {
        "businessUrl": business_url,
        "businessScreenshotUrl": screenshot_url,
        "storageId": storage_record_id,
    }
