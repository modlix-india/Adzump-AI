from datetime import datetime, timezone
from typing import Any
from structlog import get_logger

from core.models.optimization import CampaignRecommendation
from core.infrastructure.context import auth_context
from oserver.models.storage_request_model import (
    StorageReadRequest,
    StorageRequest,
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
            logger.info(
                "recommendation_previous_completed",
                campaign_id=campaign_id,
                record_id=existing["_id"],
            )

        return {"fields": doc["fields"]}

    async def _fetch_existing(self, campaign_id: str, client_code: str) -> dict | None:
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
            # keywords have origin (e.g. SEARCH_TERM, KEYWORD)
            # replace only matching origin items, preserve others
            # for non-keyword fields (e.g. age), overwrite entirely
            # TODO: handle duplicate text across origins (e.g. SEARCH_TERM and KEYWORD suggest same keyword)
            if key in ("keywords", "negativeKeywords"):
                origins = {
                    item.get("origin") for item in new_items if item.get("origin")
                }
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

    async def _fetch_by_id(self, record_id: str) -> dict | None:
        request = StorageRequest(
            storageName=self.STORAGE_NAME,
            appCode=self.APP_CODE,
            clientCode=auth_context.client_code,
            dataObjectId=record_id,
        )
        response = await self.storage.read_storage(request)
        return response.content[0] if response.success and response.content else None

    async def apply_mutation_results(
        self,
        recommendation: CampaignRecommendation,
        is_partial: bool,
    ) -> CampaignRecommendation:
        """Mark items as applied locally, handle completion status, and sync with storage."""
        # Mark fields as applied locally for the response
        fields = recommendation.fields
        updated_data = {
            name: [
                item.model_copy(update={"applied": True})
                for item in getattr(fields, name)
            ]
            for name in fields.model_fields.keys()
            if getattr(fields, name)
        }
        updated_fields_obj = fields.model_copy(update=updated_data)

        # Update completion status based on isPartial flag
        new_completed = not is_partial

        updated_recommendation = recommendation.model_copy(
            update={"fields": updated_fields_obj, "completed": new_completed}
        )

        # Sync with Storage (Perform a Merge-Update)
        if updated_recommendation.id:
            await self.sync_mutation_result(updated_recommendation, is_partial)

        return updated_recommendation

    def _merge_applied_status(
        self, existing_fields: dict, incoming_applied_fields: dict
    ) -> dict:
        """
        Merge 'applied: True' status from the mutation results into the existing stored fields.
        Uses identifying keys (resource_name, text, etc.) to match items.
        """
        # Identification priority: resource_name > text > geo_target_constant > age_range > gender_type > link_text
        ID_KEYS = [
            "resource_name",
            "text",
            "geo_target_constant",
            "age_range",
            "gender_type",
            "link_text",
        ]

        def get_uid(item):
            return next((item[k] for k in ID_KEYS if item.get(k)), None)

        for field_name, applied_items in incoming_applied_fields.items():
            if field_name not in existing_fields:
                existing_fields[field_name] = applied_items
                continue

            stored_items = existing_fields[field_name]

            # Collect IDs of items that were successfully mutated in this request
            applied_ids = {get_uid(item) for item in applied_items if get_uid(item)}

            # Mark matching items in the full storage record as applied
            for stored_item in stored_items:
                if get_uid(stored_item) in applied_ids:
                    stored_item["applied"] = True

        return existing_fields

    async def sync_mutation_result(
        self,
        recommendation: CampaignRecommendation,
        is_partial: bool,
    ):
        """Update storage by merging applied status from the current mutation into the full record."""
        if not recommendation.id:
            return

        if is_partial:
            # Fetch full record to avoid deleting other recommendations in a partial update
            existing = await self._fetch_by_id(recommendation.id)
            if not existing:
                logger.error(
                    "storage_sync_failed_record_missing", record_id=recommendation.id
                )
                return

            # Merge 'applied' status into existing fields
            applied_fields_dump = recommendation.fields.model_dump(exclude_none=True)
            fields_to_store = self._merge_applied_status(
                existing.get("fields", {}), applied_fields_dump
            )
        else:
            # If isPartial is False, the payload contains the entire storage object.
            # We can directly use the incoming fields (already marked as applied locally).
            fields_to_store = recommendation.fields.model_dump(exclude_none=True)

        # Perform a partial update on the storage document
        request = StorageUpdateWithPayload(
            storageName=self.STORAGE_NAME,
            appCode=self.APP_CODE,
            dataObjectId=recommendation.id,
            dataObject={
                "fields": fields_to_store,
                "completed": recommendation.completed,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            },
            isPartial=True,  # Crucial: only update specified fields
        )
        await self.storage.update_storage(request)
        logger.info(
            "recommendation_storage_synced_applied",
            campaign_id=recommendation.campaign_id,
            is_partial=is_partial,
        )


recommendation_storage_service = RecommendationStorageService()
