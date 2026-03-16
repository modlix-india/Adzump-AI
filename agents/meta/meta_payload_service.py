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
        campaign_input = meta_input_payload["campaign"]
        adset_input = meta_input_payload["adset"]
        creative_input = meta_input_payload["creative"]
        ad_input = meta_input_payload["ad"]

        # Detect dynamic creative
        is_dynamic = MetaPayloadAssemblyService._is_dynamic_creative(
            creative_input
        )

        # Build campaign
        campaign_payload = build_campaign_payload(campaign_input)

        logger.info(
            "Campaign payload built",
            campaign_payload=campaign_payload
        )
        

        if is_dynamic:
            adset_input["is_dynamic_creative"] = True
            print("Dynamic creative detected")
        
        # Build adset
        adset_payload = build_adset_payload(adset_input)

        logger.info(
            "Adset payload built",
            adset_payload=adset_payload,
            is_dynamic=is_dynamic
        )

        # Build creative (pass dynamic flag)
        creative_payload = build_creative_payload(
            meta_input_payload,
            is_dynamic=is_dynamic
        )
        logger.info(
            "Creative payload built",
            creative_payload=creative_payload,
            is_dynamic=is_dynamic
        )

        # Build ad
        lead_gen_form_id = meta_input_payload["creative"].get("call_to_action").get("lead_gen_form_id")
        ad_payload = build_ad_payload(meta_input_payload["ad"], destination_type=meta_input_payload["adset"]["destination_type"], lead_gen_form_id=lead_gen_form_id)
        logger.info(
            "Ad payload built",
            ad_payload=ad_payload,
            is_dynamic=is_dynamic
        )


        return {
            "campaign_payload": campaign_payload,
            "adset_payload": adset_payload,
            "creative_payload": creative_payload,
            "ad_payload": ad_payload
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
        )

