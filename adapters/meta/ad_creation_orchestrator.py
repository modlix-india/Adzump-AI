from core.models.meta import CreateMetaAdRequest
from structlog import get_logger
from adapters.meta.exceptions import MetaAdCreationError
from agents.meta.meta_payload_service import MetaPayloadAssemblyService
from adapters.meta.meta_ad_executor import MetaAdExecutor
from core.models.meta import AdCreationStage

logger = get_logger(__name__)


class MetaAdCreationOrchestrator:
    def __init__(self, meta_client, ad_account_id: str):
        self.meta_client = meta_client
        self.ad_account_id = ad_account_id

        self.meta_executor = MetaAdExecutor(
            meta_client,
            ad_account_id,
        )

    async def create_full_structure(
        self, meta_input_payload: CreateMetaAdRequest, inspect_payload: bool
    ) -> dict:

        meta_input_payload = meta_input_payload.model_dump(
            mode="json", exclude_none=True
        )
        existing_ids = meta_input_payload.get("existing_ids") or {
            "campaign_id": None,
            "adset_id": None,
            "creative_id": None,
            "ad_id": None,
        }

        current_stage = AdCreationStage.ASSEMBLY

        try:
            assembled_payloads = MetaPayloadAssemblyService.assemble_meta_payloads(
                meta_input_payload
            )

            # Inspect payload - Dry run — return assembled payloads without hitting Meta API
            if inspect_payload:
                return {"status": "SUCCESS", "payloads": assembled_payloads}

            current_stage = AdCreationStage.CAMPAIGN
            if not existing_ids["campaign_id"]:
                existing_ids["campaign_id"] = await self.meta_executor.create_campaign(
                    assembled_payloads["campaign_payload"]
                )

                logger.info(
                    "Campaign created",
                    ad_account_id=self.ad_account_id,
                    campaign_id=existing_ids["campaign_id"],
                )

            current_stage = AdCreationStage.ADSET

            # AdSet
            if not existing_ids["adset_id"]:
                adset_payload = assembled_payloads["adset_payload"]
                adset_payload["campaign_id"] = existing_ids["campaign_id"]

                existing_ids["adset_id"] = await self.meta_executor.create_adset(
                    adset_payload
                )

                logger.info(
                    "Adset created",
                    ad_account_id=self.ad_account_id,
                    adset_id=existing_ids["adset_id"],
                )

            current_stage = AdCreationStage.CREATIVE

            # Creative
            if not existing_ids["creative_id"]:
                existing_ids["creative_id"] = await self.meta_executor.create_creative(
                    assembled_payloads["creative_payload"]
                )

                logger.info(
                    "Creative created",
                    ad_account_id=self.ad_account_id,
                    creative_id=existing_ids["creative_id"],
                )

            current_stage = AdCreationStage.AD

            # Ad
            if not existing_ids["ad_id"]:
                ad_payload = {
                    **assembled_payloads["ad_payload"],
                    "adset_id": existing_ids["adset_id"],
                    "creative": {"creative_id": existing_ids["creative_id"]},
                }
                existing_ids["ad_id"] = await self.meta_executor.create_ad(ad_payload)

                logger.info(
                    "Ad created",
                    ad_account_id=self.ad_account_id,
                    ad_id=existing_ids["ad_id"],
                )

            return {"status": "SUCCESS", "ids": existing_ids}

        except Exception as exc:
            raise MetaAdCreationError(
                failed_stage=current_stage.value,
                existing_ids=existing_ids,
                original_exc=exc,
            ) from exc
