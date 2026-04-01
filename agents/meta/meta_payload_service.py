from structlog import get_logger
from agents.meta.payload_builders.campaign_builder import build_campaign_payload
from agents.meta.payload_builders.adset_builder.adset_builder import build_adset_payload
from agents.meta.payload_builders.creative_builder import build_creative_payload
from agents.meta.payload_builders.ad_builder import build_ad_payload

logger = get_logger(__name__)


class MetaPayloadAssemblyService:
    """
    Assembles Meta Ads payloads from the unified input contract.
    - Detects dynamic creative automatically
    """

    @staticmethod
    def assemble_meta_payloads(meta_input_payload: dict) -> dict:
        campaign_input = meta_input_payload.get("campaign")
        adset_input = meta_input_payload.get("adset")
        creative_input = meta_input_payload.get("creative")

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
            meta_input_payload, is_dynamic=is_dynamic_creative
        )
        logger.info(
            "Creative payload built",
            creative_payload=creative_payload,
            is_dynamic=is_dynamic_creative,
        )

        # Build ad

        ad_payload = build_ad_payload(meta_input_payload.get("ad"))
        logger.info(
            "Ad payload built", ad_payload=ad_payload, is_dynamic=is_dynamic_creative
        )

        return {
            "campaign_payload": campaign_payload,
            "adset_payload": adset_payload,
            "creative_payload": creative_payload,
            "ad_payload": ad_payload,
        }

    @staticmethod
    def _is_dynamic_creative(creative: dict) -> bool:
        """
        Detects whether creative should be dynamic.
        Rule:
        - If any variation array has more than 1 element → dynamic
        """

        return (
            len(creative.get("primary_texts", [])) > 1
            or len(creative.get("headlines", [])) > 1
            or len(creative.get("image_hashes", [])) > 1
            or len(creative.get("descriptions", [])) > 1
        )
