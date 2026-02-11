from datetime import datetime, timezone
from typing import Any
from structlog import get_logger

from core.models.optimization import CampaignRecommendation
from oserver.models.storage_request_model import (
    StorageReadRequest,
    StorageRequestWithPayload,
    StorageUpdateWithPayload,
    FilterCondition,
    ComplexCondition,
)
from oserver.services.storage_service import StorageService

logger = get_logger(__name__)

class RecommendationStorageService:
    STORAGE_NAME = "campaignSuggestions"
    APP_CODE = "marketingai"

    def __init__(self) -> None:
        self.storage = StorageService()

    async def store(
        self, recommendation: CampaignRecommendation, client_code: str
    ) -> dict:
        campaign_id = recommendation.campaign_id
        existing = await self._fetch_existing(campaign_id, client_code)

        base_fields = existing.get("fields", {}) if existing else None

        doc = self._build_recommendation(recommendation, base_fields)
        await self._create(doc)
        logger.info("recommendation_created", campaign_id=campaign_id)

        if existing:
            await self._mark_completed(existing["_id"])
            logger.info("recommendation_previous_completed", campaign_id=campaign_id, record_id=existing["_id"])

        return {"fields": doc["fields"]}

    async def _fetch_existing(
        self, campaign_id: str, client_code: str
    ) -> dict | None:
        request = StorageReadRequest(
            storageName=self.STORAGE_NAME,
            appCode=self.APP_CODE,
            clientCode=client_code,
            filter=ComplexCondition(
                operator="AND",
                conditions=[
                    FilterCondition(field="campaign_id", value=campaign_id),
                    FilterCondition(field="completed", operator="IS_FALSE"),
                ],
            ),
            size=1,
        )
        response = await self.storage.read_page_storage(request)
        return response.content[0] if response.content else None

    def _build_recommendation(
        self, rec: CampaignRecommendation, base_fields: dict | None
    ) -> dict:
        fields = self._merge_fields(rec, base_fields)
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "platform": rec.platform,
            "parent_account_id": rec.parent_account_id,
            "account_id": rec.account_id,
            "product_id": rec.product_id,
            "campaign_id": rec.campaign_id,
            "campaign_name": rec.campaign_name,
            "campaign_type": rec.campaign_type,
            "completed": False,
            "fields": fields,
        }

    def _merge_fields(
        self, rec: CampaignRecommendation, base_fields: dict | None
    ) -> dict:
        fields = dict[Any, Any](base_fields) if base_fields else {}
        rec_fields = rec.fields.model_dump(exclude_none=True)
        for key, new_items in rec_fields.items():
            for item in new_items:
                item["applied"] = False
            existing = fields.get(key, [])
            # keywords have origin (e.g. SEARCH_TERM, KEYWORD_PLANNER)
            # replace only matching origin items, preserve others
            # for non-keyword fields (e.g. age), overwrite entirely
            if key in ("keywords", "negativeKeywords"):
                origins = {item.get("origin") for item in new_items if item.get("origin")}
                kept = [item for item in existing if item.get("origin") not in origins]
                fields[key] = kept + new_items
            else:
                fields[key] = new_items
        return fields

    async def _create(self, doc: dict):
        request = StorageRequestWithPayload(
            storageName=self.STORAGE_NAME,
            appCode=self.APP_CODE,
            dataObject=doc,
        )
        return await self.storage.write_storage(request)

    async def _mark_completed(self, record_id: str):
        request = StorageUpdateWithPayload(
            storageName=self.STORAGE_NAME,
            appCode=self.APP_CODE,
            dataObjectId=record_id,
            dataObject={"completed": True},
        )
        return await self.storage.update_storage(request)


recommendation_storage_service = RecommendationStorageService()
