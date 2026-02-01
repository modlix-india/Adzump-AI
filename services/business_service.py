import json
from typing import List

from fastapi import HTTPException
from structlog import get_logger  # type: ignore

from exceptions.custom_exceptions import (
    AIProcessingException,
    BusinessValidationException,
)
from models.business_model import BusinessMetadata, WebsiteSummaryResponse
from oserver.models.storage_request_model import (
    StorageFilter,
    StorageReadRequest,
    StorageRequest,
    StorageRequestWithPayload,
    StorageUpdateWithPayload,
)
from oserver.services.storage_service import StorageService
from services.openai_client import chat_completion
from services.scraper_service import scrape_website
from utils import prompt_loader
from utils.helpers import normalize_url

logger = get_logger(__name__)


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
            clientCode=client_code,
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

    # TODO: Refactor - extract summary fetching logic to StorageService.fetch_business_summary()
    async def process_website_data(
        self,
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
            existing_data_response = await storage_service.read_page_storage(
                read_request
            )

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
                return WebsiteSummaryResponse(
                    storage_id=existing_id,
                    business_url=website_url,
                    business_type=existing_businessType,
                    summary=existing_summary,
                    final_summary=existing_finalSummary,
                )

            # STEP 3: SCRAPE WEBSITE
            logger.info(f"Scraping website: {website_url}")
            scraped_data = await scrape_website(website_url)

            if not scraped_data:
                raise HTTPException(status_code=500, detail="Failed to scrape website")

            # STEP 4: GENERATE SUMMARY USING LLM
            logger.info(f"Generating summary for {website_url}")
            summary_raw = await self.generate_website_summary(scraped_data)

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

                await storage_service.update_storage(update_payload)
                logger.info("Storage is updated successfully")
                return WebsiteSummaryResponse(
                    storage_id=existing_id,
                    business_url=website_url,
                    business_type=businessType,
                    summary=summary_text,
                    final_summary=summary_text,
                )

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

            return WebsiteSummaryResponse(
                storage_id=new_storage_id,
                business_url=website_url,
                business_type=businessType,
                summary=summary_text,
                final_summary=summary_text,
            )

        except HTTPException:
            raise

        except Exception as e:
            logger.exception(f"Unexpected error in process_website_data: {e}")
            raise HTTPException(
                status_code=500,
                detail="Internal server error during website processing",
            )

    async def generate_website_summary(self, scraped_data: dict) -> str:
        if not scraped_data:
            raise BusinessValidationException(
                "Scraped data is required for summary generation"
            )

        try:
            prompt = prompt_loader.format_prompt(
                "business/website_summary_prompt.txt", scraped_data=scraped_data
            )
            response = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.OPENAI_MODEL,
                max_tokens=500,
                temperature=0.2,
            )
            logger.info("Summary generated successfully")
            logger.debug(f"Summary response: {response}")
            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            raise AIProcessingException("Failed to generate summary")
