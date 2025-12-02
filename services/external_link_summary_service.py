import json
import logging
from fastapi import HTTPException
from services.business_service import generate_website_summary
from services.scraper_service import scrape_website
from utils.helpers import normalize_url
from oserver.models.storage_request_model import (
    StorageFilter,
    StorageReadRequest,
    StorageUpdateWithPayload,
)
from oserver.services.storage_service import StorageService
from services.final_summary_service import generate_final_summary

logger = logging.getLogger(__name__)


async def process_external_link(
    external_url: str,
    business_url: str,
    access_token: str,
    client_code: str,
    x_forwarded_host: str,
    x_forwarded_port: str,
    rescrape: bool = False,
):
    logger.info("[ExternalLink] Starting external link summary pipeline")
    # Normalize inputs strongly
    business_url = normalize_url(business_url)
    external_url = normalize_url(external_url)
    # STEP 1: Fetch product record
    read_request = StorageReadRequest(
        storageName="AISuggestedData",
        appCode="marketingai",
        clientCode=client_code,
        filter=StorageFilter(field="businessUrl", value=business_url),
    )
    storage_service = StorageService(
        access_token=access_token,
        client_code=client_code,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port,
    )
    logger.info("[ExternalLink] Checking business record in storage...")
    record_response = await storage_service.read_page_storage(read_request)
    if not record_response.success:
        raise HTTPException(500, "Storage read failed in external summary service")
    records = (
        record_response.result[0].get("result", {}).get("result", {}).get("content", [])
    )
    if not records:
        raise HTTPException(404, "No record found for this businessUrl")
    record = records[-1]
    storage_id = record.get("_id")
    existing_links = record.get("externalLinks", [])
    # STEP 2: DEDUPE EXTERNAL LINKS
    deduped_links = {}
    for item in existing_links:
        url_key = normalize_url(item.get("url", ""))
        deduped_links[url_key] = item
    existing_links = list(deduped_links.values())
    # STEP 3: Check if external link exists already
    existing_external_item = None
    for link in existing_links:
        if normalize_url(link.get("url", "")) == external_url:
            existing_external_item = link
            break
    # CASE A — External link exists
    if existing_external_item:
        existing_summary = existing_external_item.get("urlSummary")
        # CASE A1 — Summary exists & rescrape=False → return cached
        if existing_summary and not rescrape:
            logger.info("[ExternalLink] Returning cached external summary")
            return {
                "externalUrl": external_url,
                "externalSummary": existing_summary,
                "finalSummary": record.get("finalSummary", ""),
                "storageId": storage_id,
            }
        # CASE A2 — Summary missing OR rescrape=True → regenerate
        logger.info(
            "[ExternalLink] Summary missing or rescrape=True → regenerating external summary"
        )
    else:
        # CASE B — External link does NOT exist → scrape and add new
        logger.info("[ExternalLink] New external URL → creating new summary entry")
    # STEP 4: SCRAPE the external URL
    scraped_data = await scrape_website(url=external_url)
    logger.info(f"[ExternalLink] Scraped Data: {bool(scraped_data)}")
    # Robust validate scraped data
    if not scraped_data or ("content" in scraped_data and not scraped_data["content"]):
        raise HTTPException(500, "Scraper returned empty content for external website")
    # STEP 5: LLM SUMMARY GENERATION
    logger.info(f"[ExternalLink] Generating summary for {external_url}")
    summary_raw = await generate_website_summary(scraped_data)
    try:
        parsed = json.loads(summary_raw)
    except:
        parsed = json.loads(summary_raw.replace("'", '"'))
    summary_text = parsed.get("summary", "")
    # STEP 6: UPDATE OR APPEND external link summary
    updated_links = existing_links.copy()
    if existing_external_item:
        # Update only this external entry
        existing_external_item["urlSummary"] = summary_text
    else:
        # Append new external entry
        updated_links.append({"url": external_url, "urlSummary": summary_text})
    # Reflect updates back
    updated_links_final = updated_links
    logger.info("[ExternalLink] Updating externalLinks array in storage")
    update_request = StorageUpdateWithPayload(
        storageName="AISuggestedData",
        dataObjectId=storage_id,
        clientCode=client_code,
        appCode="",
        dataObject={"externalLinks": updated_links_final},
    )
    update_result = await storage_service.update_storage(update_request)
    logger.info(f"[ExternalLink] Storage update success: {update_result.success}")
    if not update_result.success:
        logger.error("[ExternalLink] Failed to update externalLinks array")
        raise HTTPException(500, "Failed to update externalLinks in storage")
    logger.info("[ExternalLink] External summary stored successfully")
    # STEP 7: SAFE FINAL SUMMARY REGENERATION
    logger.info("[ExternalLink] Regenerating final summary...")
    try:
        final_summary_result = await generate_final_summary(
            business_url=business_url,
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port,
        )
        merged_final_summary = final_summary_result.get("finalSummary", "")
    except Exception as e:
        logger.exception(
            f"[ExternalLink] Final summary generation failed — keeping previous finalSummary {e}"
        )
        merged_final_summary = record.get("finalSummary", "")
    # STEP 8: RETURN RESPONSE
    return {
        "externalUrl": external_url,
        "externalSummary": summary_text,
        "finalSummary": merged_final_summary,
        "storageId": storage_id,
    }
