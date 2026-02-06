# TODO: Remove after trust in new search term optimization service (core/services/search_term_analyzer.py)
from datetime import datetime
from structlog import get_logger  # type: ignore

from services.search_term_pipeline import SearchTermPipeline
from oserver.services.storage_service import StorageService
from oserver.models.storage_request_model import (
    StorageReadRequest,
    StorageRequestWithPayload,
    StorageUpdateWithPayload,
    StorageFilter,
)

logger = get_logger(__name__)


async def process_search_terms(
    *,
    client_code: str,
    customer_id: str,
    login_customer_id: str,
    campaign_id: str,
    duration: str,
    access_token: str,
    ai_suggestions: list = None,  # optional, can pass precomputed suggestions
) -> dict:
    """
    Orchestrates search term suggestion flow using NCLC storage directly.

    - Works for any suggestion_type: searchTerms, keywords, age, gender, headlines, etc.
    - Stores data under 'suggestedData' per schema
    - Sets default sourceType and status dynamically
    """

    logger.info("Starting search term service", campaign_id=campaign_id)

    # Run pipeline if no precomputed suggestions

    if ai_suggestions is None:
        pipeline = SearchTermPipeline(
            client_code=client_code,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            campaign_id=campaign_id,
            duration=duration,
            access_token=access_token,
        )
        pipeline_result = await pipeline.run_pipeline()
        ai_suggestions = pipeline_result.get("classified_search_terms", [])
        customer_id = pipeline_result.get("customerId")

        campaign_name = pipeline_result.get("campaignName")
        product_id = pipeline_result.get("productId")

        if not campaign_name or not product_id:
            logger.warning(
                "[SearchTermService] Pipeline returned no campaign meta; returning empty suggestions",
                campaign_id=campaign_id,
            )
            return {"searchTerms": []}
    else:
        # Use placeholder campaign_name/product_id if precomputed suggestions passed
        campaign_name = campaign_name if "campaign_name" in locals() else "Unknown"
        product_id = product_id if "product_id" in locals() else "Unknown"

    # Initialize storage service
    storage_service = StorageService(
        access_token=access_token,
        client_code=client_code,
    )

    # Read existing storage by campaignId
    read_request = StorageReadRequest(
        storageName="campaignSuggestions",
        appCode="marketingai",
        clientCode=client_code,
        filter=StorageFilter(field="campaignId", value=campaign_id),
    )
    read_response = await storage_service.read_page_storage(read_request)
    logger.info(
        "[SearchTermService] Storage read completed",
        success=read_response.success,
        campaign_id=campaign_id,
    )

    records = []
    if read_response.success and read_response.result:
        try:
            records = (
                read_response.result[0]
                .get("result", {})
                .get("result", {})
                .get("content", [])
            )
        except Exception:
            records = []

    existing_record = records[-1] if records else None
    logger.info("[SearchTermService] Existing record", record=existing_record)
    existing_id = existing_record.get("_id") if existing_record else None
    logger.info(
        "[SearchTermService] Existing record status",
        found=bool(existing_record),
        existing_id=existing_id,
        campaign_id=campaign_id,
        client_id=client_code,
        existing_record=existing_record,
    )

    today = datetime.utcnow().date()

    # Same day reuse
    if existing_record:
        updated_date_str = existing_record.get("updatedAt")

        if updated_date_str:
            updated_date = datetime.fromisoformat(updated_date_str).date()
            if updated_date == today:
                logger.info(
                    "[SearchTermService] Same day → checking cache health",
                    campaign_id=campaign_id,
                )
                fields = existing_record.get("fields", {})
                suggestion_list = fields.get("searchTerms", [])
                suggestion_entry = suggestion_list[0] if suggestion_list else {}
                cached_data = suggestion_entry.get("suggestedData", [])

                # Force refresh if stale raw_response exists in any evaluation
                has_corrupted_data = any(
                    "raw_response"
                    in str(s.get("evaluations", {}).get("relevancyCheck", {}))
                    for s in cached_data
                )

                if not has_corrupted_data and cached_data:
                    logger.info(
                        "[SearchTermService] Cache is healthy and has data → reuse existing suggestions",
                        campaign_id=campaign_id,
                    )
                    return {"searchTerms": cached_data}

                if not cached_data:
                    logger.info(
                        "[SearchTermService] Cache is empty → bypassing reuse",
                        campaign_id=campaign_id,
                    )
                else:
                    logger.warning(
                        "[SearchTermService] Corrupted cache detected (raw_response) → bypassing same-day reuse",
                        campaign_id=campaign_id,
                    )

    # Normalize fields for schema compliance
    if existing_record:
        fields = existing_record.get("fields", {})
    else:
        fields = {}

    # Ensure dynamic searchTerms exists as a list
    suggestion_list = fields.get("searchTerms", [])
    suggestion_entry = suggestion_list[0] if suggestion_list else {}
    suggestion_entry["suggestedData"] = ai_suggestions
    suggestion_entry.setdefault("status", "OPEN")
    suggestion_entry.setdefault(
        "sourceType",
        "SEARCH TERM ANALYSIS",
    )

    fields["searchTerms"] = [suggestion_entry]

    # CREATE or UPDATE storage
    if not existing_id:
        logger.info("No storage found → creating new")
        create_payload = StorageRequestWithPayload(
            storageName="campaignSuggestions",
            clientCode=client_code,
            appCode="marketingai",
            dataObject={
                "updatedAt": datetime.utcnow().isoformat(),
                "campaignId": campaign_id,
                "customerId": customer_id,
                "campaignName": campaign_name,
                "productId": product_id,
                "completed": False,
                "campaignType": "SEARCH",
                "platform": "GOOGLE",
                "fields": fields,
            },
        )
        result = await storage_service.write_storage(create_payload)
        logger.info(
            "[SearchTermService] Storage created successfully",
            success=result.success,
            campaign_id=campaign_id,
        )
    else:
        logger.info(
            "[SearchTermService] Updating existing storage", campaign_id=campaign_id
        )
        update_payload = StorageUpdateWithPayload(
            storageName="campaignSuggestions",
            clientCode=client_code,
            appCode="marketingai",
            dataObjectId=existing_id,
            dataObject={
                "updatedAt": datetime.utcnow().isoformat(),
                "fields": fields,
            },
        )
        result = await storage_service.update_storage(update_payload)
        logger.info(
            "[SearchTermService] Storage updated successfully",
            success=result.success,
            campaign_id=campaign_id,
        )

    return {"searchTerms": ai_suggestions}
