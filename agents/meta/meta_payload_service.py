import asyncio
from structlog import get_logger
from core.models.meta import MetaAdCreationRequest, CreativePayload, AssembledMetaPayloads
from agents.meta.payload_builders.basic_entity_builders import (
    build_campaign_payload,
    build_ad_payload,
)
from agents.meta.payload_builders.adset_builder.adset_builder import build_adset_payload
from agents.meta.payload_builders.creative_builder import build_creative_payload

logger = get_logger(__name__)


class MetaPayloadAssemblyService:
    """Orchestrate parallel assembly of Meta API payloads from a unified request."""

    @staticmethod
    async def assemble_meta_payloads(
        meta_request: MetaAdCreationRequest,
    ) -> AssembledMetaPayloads:
        """Assemble Campaign, AdSet, Creative, and Ad payloads concurrently."""
        creative_input = meta_request.creative

        is_dynamic_creative = MetaPayloadAssemblyService._is_dynamic_creative(
            creative_input
        )

        async def _run_task(name: str, func, *args) -> dict:
            try:
                return await asyncio.to_thread(func, *args)
            except Exception as e:
                logger.error("Meta payload assembly failed", component=name, error=str(e))
                raise

        # Build payloads in parallel
        (
            campaign_payload,
            adset_payload,
            creative_payload,
            ad_payload,
        ) = await asyncio.gather(
            _run_task("campaign", build_campaign_payload, meta_request.campaign),
            _run_task(
                "adset", build_adset_payload, meta_request.adset, is_dynamic_creative
            ),
            _run_task(
                "creative",
                build_creative_payload,
                creative_input,
                is_dynamic_creative,
            ),
            _run_task("ad", build_ad_payload, meta_request.ad),
        )

        logger.info(
            "Meta payloads assembled successfully",
            is_dynamic=is_dynamic_creative,
            components=["campaign", "adset", "creative", "ad"],
        )

        return AssembledMetaPayloads(
            campaign_payload=campaign_payload,
            adset_payload=adset_payload,
            creative_payload=creative_payload,
            ad_payload=ad_payload,
        )

    @staticmethod
    def _is_dynamic_creative(creative: CreativePayload) -> bool:
        """Return True if any asset (text/headline/image) has multiple variations."""

        return (
            len(creative.primary_texts) > 1
            or len(creative.headlines) > 1
            or len(creative.image_hashes) > 1
            or (creative.descriptions is not None and len(creative.descriptions) > 1)
        )
