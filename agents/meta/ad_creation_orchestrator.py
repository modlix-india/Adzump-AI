from structlog import get_logger
from adapters.meta.exceptions import MetaAPIError
from agents.meta.meta_payload_service import (
    MetaPayloadAssemblyService
)
from agents.meta.executors.campaign_executor import MetaCampaignExecutor
from agents.meta.executors.adset_executor import MetaAdSetExecutor
from agents.meta.executors.creative_executor import MetaCreativeExecutor
from agents.meta.executors.ad_creation_executor import MetaAdExecutor

logger = get_logger(__name__)


class MetaAdCreationOrchestrator:

    def __init__(self, meta_client, ad_account_id: str, client_code: str):
        self.meta_client = meta_client
        self.ad_account_id = ad_account_id
        self.client_code = client_code

        self.campaign_executor = MetaCampaignExecutor(
            meta_client, ad_account_id, client_code
        )
        self.adset_executor = MetaAdSetExecutor(
            meta_client, ad_account_id, client_code
        )
        self.creative_executor = MetaCreativeExecutor(
            meta_client, ad_account_id, client_code
        )
        self.ad_executor = MetaAdExecutor(
            meta_client, ad_account_id, client_code
        )

    async def create_full_structure(self, meta_input_payload: dict) -> dict:

        existing_ids = meta_input_payload.get("existing_ids") or {
            "campaign_id": None,
            "adset_id": None,
            "creative_id": None,
            "ad_id": None,
        }

        assembled_payloads = (
            MetaPayloadAssemblyService.assemble_meta_payloads(
                meta_input_payload
            )
        )

        current_stage = "CAMPAIGN"

        try:
            # Campaign
            if not existing_ids["campaign_id"]:
                existing_ids["campaign_id"] = (
                    await self.campaign_executor.create_campaign(
                        assembled_payloads["campaign_payload"]
                    )
                )

                logger.info(
                    "Campaign created",
                    campaign_id=existing_ids["campaign_id"]
                )

            current_stage = "ADSET"

            # AdSet
            if not existing_ids["adset_id"]:
                existing_ids["adset_id"] = (
                    await self.adset_executor.create_adset(
                        assembled_payloads["adset_payload"],
                        existing_ids["campaign_id"]
                    )
                )

                logger.info(
                    "Adset created",
                    adset_id=existing_ids["adset_id"]
                )
                

            current_stage = "CREATIVE"

            # Creative
            if not existing_ids["creative_id"]:
                existing_ids["creative_id"] = (
                    await self.creative_executor.create_creative(
                        assembled_payloads["creative_payload"]
                    )
                )

                logger.info(
                    "Creative created",
                    creative_id=existing_ids["creative_id"]
                )

            current_stage = "AD"

            # Ad
            if not existing_ids["ad_id"]:
                existing_ids["ad_id"] = (
                    await self.ad_executor.create_ad(
                        assembled_payloads["ad_payload"],
                        existing_ids["adset_id"],
                        existing_ids["creative_id"]
                    )
                )

                logger.info(
                    "Ad created",
                    ad_id=existing_ids["ad_id"]
                )

            return {
                "status": "SUCCESS",
                "ids": existing_ids
            }

        except MetaAPIError as exc:
            return {
                "status": "FAILED",
                "failed_stage": current_stage,
                "error": {
                    "message": exc.message,
                    "status_code": exc.status_code,
                    "meta_error": exc.error_data.get("error", {})
                },
                "ids": existing_ids
            }

