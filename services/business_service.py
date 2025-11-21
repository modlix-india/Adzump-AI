import logging
import json
from typing import List, Tuple
from pydantic import ValidationError
from services.scraper_service import scrape_website
from services.summary_service import generate_summary
from utils import prompt_loader
from models.business_model import BusinessMetadata
from http.client import HTTPException
from oserver.models.storage_request_model import StorageFilter, StorageReadRequest, StorageRequest, StorageRequestWithPayload
from oserver.services.storage_service import read_storage, read_storage_page, write_storage
from services.openai_client import chat_completion

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BusinessService:

    OPENAI_MODEL = "gpt-4o-mini"

    async def extract_business_metadata(
        self, scraped_data: str, url: str = None
    ) -> BusinessMetadata:
        prompt = prompt_loader.format_prompt(
                'business_metadata_prompt.txt',
                scraped_data=scraped_data,
                url=url
            )
        try:
            resp = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.OPENAI_MODEL,
                max_tokens=500,
                temperature=0.1,
                response_format={"type": "json_object"}
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
            'business_usp_prompt.txt',
            scraped_data=scraped_data
        )

        try:
            resp = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.OPENAI_MODEL,
                max_tokens=400,
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            usp_data = json.loads(resp.choices[0].message.content.strip())
            unique_features = usp_data.get("features", [])

            logger.info(
                f"Extracted and validated USPs: {unique_features}"
            )
            return unique_features

        except Exception as e:
            logger.warning(f"USP extraction failed: {e}")
            return []

    @staticmethod
    async def fetch_product_details(data_object_id: str, access_token: str, client_code: str):
        payload = StorageRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            dataObjectId=data_object_id,
            eager=False,
            eagerFields=[]
        )
        response = await read_storage(payload, access_token, client_code)
        if not response.success or not response.result:
            raise HTTPException(status_code=500, detail=response.error or "Failed to fetch product details")
        data = response.result
        try:
            if isinstance(data, list) and len(data) > 0:
                product_data = data[0]["result"]["result"]
            elif isinstance(data, dict) and "result" in data:
                product_data = data["result"]["result"]
            else:
                raise HTTPException(status_code=500, detail="Unexpected product data format")
        except (KeyError, IndexError, TypeError):
            raise HTTPException(status_code=500, detail="Invalid product data response structure")
        return product_data


async def process_website_data(website_url: str, access_token: str, client_code: str,x_forwarded_host: str, x_forwarded_port: str):
    try:
        # --- Step 1: Check if the data already exists in storage ---
        logger.info(f"Checking if {website_url} already exists in storage")

        read_request = StorageReadRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            clientCode=client_code,
            filter=StorageFilter(
                field="businessUrl",
                value=website_url
            )
        )

        existing_data_response = await read_storage_page(
            request=read_request,
            access_token=access_token,
            client_code=client_code,
        )

        if existing_data_response.success:
            try:
                # Extract from response
                existing_records = (
            existing_data_response.result[0]
            .get("result", {})
            .get("result", {})
            .get("content", [])
        )
                if existing_records:
                    existing_record = existing_records[-1]
                    existing_id = existing_record.get("_id")
                    existing_summary = existing_record.get("summary", "")
                    existing_screenshot = existing_record.get("screenshot")

                    logger.info(f"Found existing record for {website_url}, returning from storage")

                    return {
                        "websiteUrl": website_url,
                        "summary": existing_summary,
                        "screenshotUrl": existing_screenshot,
                        "storageId": existing_id,
                    }
            except Exception as e:
                logger.warning(f"Error parsing existing storage data: {e}")

        # --- Step 2: If not found, proceed with scraping ---
        logger.info(f"Scraping website: {website_url}")
        scraped_data = await scrape_website(
            website_url,
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port
        )
        if not scraped_data:
            raise HTTPException(status_code=500, detail="Failed to scrape website")
        logger.info(f"Generating summary for {website_url}")
        summary_result = await generate_summary(scraped_data)
        summary_text = summary_result.get("summary", "")
        payload = {
            "storageName": "AISuggestedData",
            "dataObject": {
                "summary": summary_text,
                "businessUrl": website_url,
                "siteLinks": scraped_data.get("links", []),
                "screenshot": scraped_data.get("screenshot"),
            },
            "eagerFields": [],
            "eager": False,
            "appCode": "",
            "clientCode": client_code
        }
        storage_request = StorageRequestWithPayload(**payload)
        logger.info(f"Creating document in storage for {website_url}")
        storage_response = await write_storage(
            storage_request,
            access_token=access_token,
            client_code=client_code
        )
        if not storage_response.success:
            raise HTTPException(status_code=500, detail=f"Storage failed: {storage_response.error}")
        storage_id = None
        try:
            storage_records = storage_response.result
            if isinstance(storage_records, list) and len(storage_records) > 0:
                storage_id = (
                    storage_records[0]
                    .get("result", {})
                    .get("result", {})
                    .get("_id", None)
                )
            else:
                storage_id = None
        except (KeyError, TypeError, IndexError) as e:
            logger.error(f"Error extracting storageId: {e}")
            storage_id = None

        logger.info(f"Extracted Storage ID: {storage_id}")

        return {
            "websiteUrl": website_url,
            "summary": summary_text,
            "screenshotUrl": scraped_data.get("screenshot"),
            "storageId": storage_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error in analyze_and_store_website: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during analysis")

async def fetch_products_summary(
    website_url: str,
    access_token: str,
    client_code: str
):
    try:
        logger.info(f"Fetching product summary for {website_url}")

        read_request = StorageReadRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            clientCode=client_code,
            filter=StorageFilter(
                field="businessUrl",
                value=website_url
            )
        )

        existing_data_response = await read_storage_page(
            request=read_request,
            access_token=access_token,
            client_code=client_code,
        )

        if existing_data_response.success:
            try:
                records = (
                    existing_data_response.result[0]
                    .get("result", {})
                    .get("result", {})
                    .get("content", [])
                )

                if records:
                    record = records[-1]
                    id = record.get("_id")

                    summary = record.get("summary", "")
                    external_links = record.get("externalLinks", [])
                    assets = record.get("assets", [])

                    external_links_summary = [
                        {
                            "url": link.get("url"),
                            "urlSummary": link.get("urlSummary") or link.get("summary")
                        }
                        for link in external_links
                    ]

                    assets_summary = [
                        {
                            "fileName": asset.get("fileName"),
                            "fileSummary": asset.get("fileSummary") or asset.get("summary")
                        }
                        for asset in assets
                    ]

                    return {
                        "websiteUrl": website_url,
                        "summary": summary,
                        "externalLinksSummary": external_links_summary,
                        "assetsSummary": assets_summary,
                        "storageId": id,
                        "storageObject": record
                    }

            except Exception as e:
                logger.warning(f"Error parsing storage data: {e}")

        return {
            "websiteUrl": website_url,
            "summary": "",
            "externalLinksSummary": [],
            "assetsSummary": [],
            "storageObject": {}
        }

    except Exception as e:
        logger.error(f"Error fetching product summary: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
