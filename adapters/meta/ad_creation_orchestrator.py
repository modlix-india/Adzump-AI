from core.models.meta import CreateMetaAdRequest
from structlog import get_logger
from adapters.meta.exceptions import MetaAdCreationError
from agents.meta.meta_payload_service import MetaPayloadAssemblyService
from adapters.meta.meta_ad_executor import MetaAdExecutor
from core.models.meta import AdCreationStage
from adapters.meta.client import meta_client
import asyncio

logger = get_logger(__name__)


class MetaAdCreationOrchestrator:

    @staticmethod
    async def create_full_structure(
        meta_request: CreateMetaAdRequest, inspect_payload: bool
    ) -> dict:

        ad_account_id = meta_request.ad_account_id
        meta_executor = MetaAdExecutor(meta_client, ad_account_id)

        existing_ids_obj = meta_request.existing_ids
        existing_ids = {
            "campaign_id": existing_ids_obj.campaign_id if existing_ids_obj else None,
            "adset_id": existing_ids_obj.adset_id if existing_ids_obj else None,
            "creative_id": existing_ids_obj.creative_id if existing_ids_obj else None,
            "ad_id": existing_ids_obj.ad_id if existing_ids_obj else None,
        }

        current_stage = AdCreationStage.ASSEMBLY

        try:
            assembled_payloads = MetaPayloadAssemblyService.assemble_meta_payloads(
                meta_request
            )

            # Inspect payload - Dry run — return assembled payloads without hitting Meta API
            if inspect_payload:
                return {
                    "status": "SUCCESS",
                    "payloads": assembled_payloads.model_dump(),
                }

            current_stage = AdCreationStage.CAMPAIGN
            if not existing_ids["campaign_id"]:
                existing_ids["campaign_id"] = await meta_executor.create_entity(
                    AdCreationStage.CAMPAIGN, assembled_payloads.campaign_payload
                )

                logger.info(
                    "Campaign created",
                    ad_account_id=ad_account_id,
                    campaign_id=existing_ids["campaign_id"],
                )

            current_stage = AdCreationStage.ADSET

            async def create_adset():
                if existing_ids["adset_id"]:
                    return existing_ids["adset_id"]

                payload = assembled_payloads.adset_payload
                payload["campaign_id"] = existing_ids["campaign_id"]

                return await meta_executor.create_entity(
                    AdCreationStage.ADSET, payload
                )

            async def create_creative():
                if existing_ids["creative_id"]:
                    return existing_ids["creative_id"]

                return await meta_executor.create_entity(
                    AdCreationStage.CREATIVE, assembled_payloads.creative_payload
                )

            results = await asyncio.gather(
                create_adset(),
                create_creative(),
                return_exceptions=True,
            )

            adset_result, creative_result = results

            # Handle AdSet
            if isinstance(adset_result, Exception):
                current_stage = AdCreationStage.ADSET
                raise adset_result
            else:
                existing_ids["adset_id"] = adset_result
                logger.info(
                    "Adset created",
                    ad_account_id=ad_account_id,
                    adset_id=existing_ids["adset_id"],
                )

            # Handle Creative
            if isinstance(creative_result, Exception):
                current_stage = AdCreationStage.CREATIVE
                raise creative_result
            else:
                existing_ids["creative_id"] = creative_result
                logger.info(
                    "Creative created",
                    ad_account_id=ad_account_id,
                    creative_id=existing_ids["creative_id"],
                )

            current_stage = AdCreationStage.AD

            # Ad
            if not existing_ids["ad_id"]:
                ad_payload = {
                    **assembled_payloads.ad_payload,
                    "adset_id": existing_ids["adset_id"],
                    "creative": {"creative_id": existing_ids["creative_id"]},
                }
                existing_ids["ad_id"] = await meta_executor.create_entity(
                    AdCreationStage.AD, ad_payload
                )

                logger.info(
                    "Ad created",
                    ad_account_id=ad_account_id,
                    ad_id=existing_ids["ad_id"],
                )

            return {"status": "SUCCESS", "ids": existing_ids}

        except Exception as exc:
            raise MetaAdCreationError(
                failed_stage=current_stage.value,
                existing_ids=existing_ids,
                original_exc=exc,
            ) from exc
