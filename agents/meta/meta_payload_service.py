from structlog import get_logger
from core.models.meta import CreateMetaAdRequest, CreativePayload, AssembledMetaPayloads
from agents.meta.payload_builders.basic_entity_builders import (
    build_campaign_payload,
    build_ad_payload,
)
from agents.meta.payload_builders.adset_builder.adset_builder import build_adset_payload
from agents.meta.payload_builders.creative_builder import build_creative_payload

logger = get_logger(__name__)


class MetaPayloadAssemblyService:
    """
    Assembles Meta Ads payloads from the unified input contract.
    - Detects dynamic creative automatically
    """

    @staticmethod
    def assemble_meta_payloads(
        meta_request: CreateMetaAdRequest,
    ) -> AssembledMetaPayloads:
        campaign_input = meta_request.campaign
        adset_input = meta_request.adset
        creative_input = meta_request.creative

        # Detect dynamic creative
        is_dynamic_creative = MetaPayloadAssemblyService._is_dynamic_creative(
            creative_input
        )

        # Build campaign
        campaign_payload = build_campaign_payload(campaign_input)

        logger.info("Campaign payload built", campaign_payload=campaign_payload)

        # Build adset
        adset_payload = build_adset_payload(adset_input, is_dynamic_creative)

        logger.info(
            "Adset payload built",
            adset_payload=adset_payload,
            is_dynamic=is_dynamic_creative,
        )

        # Build creative (pass dynamic flag)
        creative_payload = build_creative_payload(
            creative_input,
            is_dynamic=is_dynamic_creative,
        )
        logger.info(
            "Creative payload built",
            creative_payload=creative_payload,
            is_dynamic=is_dynamic_creative,
        )

        # Build ad

        ad_payload = build_ad_payload(meta_request.ad)
        logger.info(
            "Ad payload built", ad_payload=ad_payload, is_dynamic=is_dynamic_creative
        )

        return AssembledMetaPayloads(
            campaign_payload=campaign_payload,
            adset_payload=adset_payload,
            creative_payload=creative_payload,
            ad_payload=ad_payload,
        )

    @staticmethod
    def _is_dynamic_creative(creative: CreativePayload) -> bool:
        """
        Detects whether creative should be dynamic.
        Rule:
        - If any variation array has more than 1 element → dynamic
        """

        return (
            len(creative.primary_texts) > 1
            or len(creative.headlines) > 1
            or len(creative.image_hashes) > 1
            or (creative.descriptions is not None and len(creative.descriptions) > 1)
        )
