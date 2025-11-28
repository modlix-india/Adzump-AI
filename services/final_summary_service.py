import logging
from http.client import HTTPException
from oserver.models.storage_request_model import StorageFilter, StorageReadRequest, StorageUpdateWithPayload
from oserver.services.storage_service import StorageService
from utils import prompt_loader
from services.openai_client import chat_completion
from utils.helpers import normalize_url

logger = logging.getLogger(__name__)

async def generate_final_summary(
    business_url: str,
    access_token: str,
    client_code: str,
    x_forwarded_host: str,
    x_forwarded_port: str
):
    
    business_url = normalize_url(business_url)
    logger.info(f"[FinalSummary] Normalized URL: {business_url}")

    read_request = StorageReadRequest(
        storageName="AISuggestedData",
        appCode="marketingai",
        clientCode=client_code,
        filter=StorageFilter(field="businessUrl", value=business_url)
    )

    storage_service = StorageService(
        access_token=access_token,
        client_code=client_code,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port,
    )

    existing_data = await storage_service.read_page_storage(read_request)

    if not existing_data.success:
        raise HTTPException(500, "Failed to read storage for final summary")

    try:
        records = (
            existing_data.result[0]
            .get("result", {})
            .get("result", {})
            .get("content", [])
        )

        if not records:
            raise HTTPException(404, "No product data found for this businessUrl")

        record = records[-1]

    except Exception as e:
        logger.error(f"[FinalSummary] Error parsing storage response: {e}")
        raise HTTPException(500, "Invalid storage response structure")

    storage_id = record.get("_id")

    website_summary = record.get("summary", "")

    external_summary = "\n".join(
        x.get("urlSummary", "") 
        for x in record.get("externalLinks", [])
        if x.get("urlSummary")
    )

    assets_summary = "\n".join(
        a.get("fileSummary", "")
        for a in record.get("assets", [])
        if a.get("fileSummary")
    )

    logger.info("[FinalSummary] Summaries collected from record.")


    prompt = prompt_loader.format_prompt(
        "final_summary_prompt.txt",
        website_summary=website_summary,
        external_summary=external_summary,
        assets_summary=assets_summary
    )

    logger.info("[FinalSummary] Sending to LLM to generate final summary...")

    response = await chat_completion(
        messages=[{"role": "user", "content": prompt}],
        model="gpt-4o-mini",
        max_tokens=10000,
        temperature=0.2
    )

    final_summary_text = response.choices[0].message.content.strip()

    logger.info("[FinalSummary] Final summary generated successfully.")

    update_request = StorageUpdateWithPayload(
        storageName="AISuggestedData",
        dataObjectId=storage_id,
        clientCode=client_code,
        appCode="",
        dataObject={"finalSummary": final_summary_text}
    )

    update_response = await storage_service.update_storage(update_request)

    if not update_response.success:
        logger.error("[FinalSummary] Failed to update finalSummary in storage")
        raise HTTPException(500, "Failed to save final summary")

    logger.info(f"[FinalSummary] Updated successfully for ID={storage_id}")

    return {
        "businessUrl": business_url,
        "storageId": storage_id,
        "finalSummary": final_summary_text,
    }
