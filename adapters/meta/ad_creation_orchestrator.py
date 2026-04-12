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

            async def create_campaign_and_adset():
                # 1. Campaign
                campaign_id = existing_ids["campaign_id"]
                if not campaign_id:
                    campaign_id = await meta_executor.create_entity(
                        AdCreationStage.CAMPAIGN, assembled_payloads.campaign_payload
                    )
                    logger.info(
                        "Campaign created",
                        ad_account_id=ad_account_id,
                        campaign_id=campaign_id,
                    )
                    existing_ids["campaign_id"] = campaign_id

                # 2. AdSet
                adset_id = existing_ids["adset_id"]
                if not adset_id:
                    payload = assembled_payloads.adset_payload
                    payload["campaign_id"] = campaign_id
                    adset_id = await meta_executor.create_entity(
                        AdCreationStage.ADSET, payload
                    )
                    logger.info(
                        "Adset created",
                        ad_account_id=ad_account_id,
                        adset_id=adset_id,
                    )
                    existing_ids["adset_id"] = adset_id
                
                return campaign_id, adset_id

            async def create_creative():
                creative_id = existing_ids["creative_id"]
                if not creative_id:
                    creative_id = await meta_executor.create_entity(
                        AdCreationStage.CREATIVE, assembled_payloads.creative_payload
                    )
                    logger.info(
                        "Creative created",
                        ad_account_id=ad_account_id,
                        creative_id=creative_id,
                    )
                    existing_ids["creative_id"] = creative_id

                return creative_id

            results = await asyncio.gather(
                create_campaign_and_adset(),
                create_creative(),
                return_exceptions=True,
            )

            # Check for exceptions across all parallel paths
            failed_result = next((res for res in results if isinstance(res, Exception)), None)
            if failed_result:
                current_stage = (
                    AdCreationStage.CREATIVE if failed_result is results[1] 
                    else (AdCreationStage.ADSET if existing_ids["campaign_id"] else AdCreationStage.CAMPAIGN)
                )
                raise failed_result

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
