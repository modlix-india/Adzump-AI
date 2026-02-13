import structlog
from typing import List, Dict, Any
from core.models.optimization import SitelinkRecommendation
from adapters.google.mutation.mutation_config import CONFIG
from adapters.google.mutation.mutation_validator import MutationValidator
from adapters.google.mutation.mutation_context import MutationContext
from adapters.google.mutation import utils

logger = structlog.get_logger(__name__)


class SitelinkOperationBuilder:
    def __init__(self):
        self._temp_id_counter = -1
        self.validator = MutationValidator()

    async def build_sitelinks_ops(
        self,
        recommendations: List[SitelinkRecommendation],
        context: MutationContext,
    ) -> List[Dict[str, Any]]:
        operations = []
        for sitelink in recommendations:
            error = self.validator.validate_sitelink(sl=sitelink)
            if error:
                logger.error("Validation failed", error=error, text=sitelink.link_text)
                continue

            if sitelink.recommendation == "ADD":
                operations.extend(
                    self._build_add_ops(
                        customer_id=context.account_id, sitelink=sitelink
                    )
                )
            elif sitelink.recommendation == "UPDATE":
                operations.extend(
                    self._build_update_ops(
                        customer_id=context.account_id, sitelink=sitelink
                    )
                )
            elif sitelink.recommendation == "REMOVE":
                operations.extend(self._build_remove_ops(sitelink=sitelink))

        logger.info("sitelink_operations_built", count=len(operations))
        return operations

    def _build_add_ops(
        self, customer_id: str, sitelink: SitelinkRecommendation
    ) -> List[Dict[str, Any]]:
        temp_resource = f"customers/{customer_id}/assets/{self._generate_temp_id()}"
        asset_create = {
            "resourceName": temp_resource,
            "type": CONFIG.ASSET_FIELD_TYPE_SITELINK,
            "sitelinkAsset": {"linkText": sitelink.link_text},
            "finalUrls": [sitelink.final_url],
        }

        # Populate optional fields (description, etc)
        utils.populate_sitelink_fields(asset_payload=asset_create, sitelink=sitelink)

        asset_op = {"assetOperation": {"create": asset_create}}
        link_op = {
            "campaignAssetOperation": {
                "create": {
                    "asset": temp_resource,
                    "campaign": f"customers/{customer_id}/campaigns/{sitelink.campaign_id}",
                    "fieldType": CONFIG.ASSET_FIELD_TYPE_SITELINK,
                }
            }
        }
        return [asset_op, link_op]

    def _build_update_ops(
        self, customer_id: str, sitelink: SitelinkRecommendation
    ) -> List[Dict[str, Any]]:
        asset_update = {
            "resourceName": sitelink.asset_resource_name,
            "sitelinkAsset": {"linkText": sitelink.link_text},
            "finalUrls": [sitelink.final_url],
        }
        utils.populate_sitelink_fields(asset_payload=asset_update, sitelink=sitelink)

        return [
            {
                "assetOperation": {
                    "update": asset_update,
                    "updateMask": self._build_update_mask(sitelink=sitelink),
                }
            }
        ]

    def _build_remove_ops(
        self, sitelink: SitelinkRecommendation
    ) -> List[Dict[str, Any]]:
        operations = []
        if sitelink.campaign_asset_resource_name:
            operations.append(
                {
                    "campaignAssetOperation": {
                        "remove": sitelink.campaign_asset_resource_name
                    }
                }
            )
        return operations

    def _build_update_mask(self, sitelink: SitelinkRecommendation) -> str:
        fields = ["link_text", "final_urls"]
        if sitelink.description1:
            fields.append("sitelink_asset.description1")
        if sitelink.description2:
            fields.append("sitelink_asset.description2")
        if sitelink.final_mobile_url:
            fields.append("final_mobile_urls")
        if sitelink.start_date:
            fields.append("start_date_time")
        if sitelink.end_date:
            fields.append("end_date_time")
        return ",".join(fields)

    def _generate_temp_id(self) -> int:
        temp_id = self._temp_id_counter
        self._temp_id_counter -= 1
        return temp_id
