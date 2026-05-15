import asyncio
from structlog import get_logger
from core.models.meta import (
    MetaAdCreationRequest,
    CreativePayload,
    AssembledMetaPayloads,
    CreativeType,
    CreativeMode,
)
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
        adset_input = meta_request.adset

        # 1. Inference Brain: Determine Mode
        has_multiple_assets = MetaPayloadAssemblyService._has_multiple_assets(
            creative_input
        )

        if adset_input.is_dynamic_creative:
            mode = CreativeMode.DYNAMIC
        elif creative_input.type == CreativeType.CAROUSEL or not has_multiple_assets:
            mode = CreativeMode.STANDARD
        else:
            mode = CreativeMode.FLEXIBLE

        # 2. Set flags on the creative model for the builder
        creative_input.mode = mode
        creative_input.is_dynamic = mode == CreativeMode.DYNAMIC

        async def _run_task(name: str, func, *args) -> dict:
            try:
                return await asyncio.to_thread(func, *args)
            except Exception as e:
                logger.error(
                    "Meta payload assembly failed", component=name, error=str(e)
                )
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
                "adset",
                build_adset_payload,
                meta_request.adset,
                meta_request.adset.is_dynamic_creative,
            ),
            _run_task(
                "creative",
                build_creative_payload,
                creative_input,
                creative_input.is_dynamic,
            ),
            _run_task("ad", build_ad_payload, meta_request.ad),
        )

        logger.info(
            "Meta payloads assembled successfully",
            mode=mode,
            is_dynamic=creative_input.is_dynamic,
            components=["campaign", "adset", "creative", "ad"],
        )

        return AssembledMetaPayloads(
            campaign_payload=campaign_payload,
            adset_payload=adset_payload,
            creative_payload=creative_payload,
            ad_payload=ad_payload,
        )

    @staticmethod
    def _has_multiple_assets(creative: CreativePayload) -> bool:
        """Return True if any asset (text/headline/image/video) has multiple variations."""
        return (
            len(creative.primary_texts) > 1
            or len(creative.headlines) > 1
            or len(creative.image_hashes) > 1
            or len(creative.video_ids) > 1
            or (creative.descriptions is not None and len(creative.descriptions) > 1)
        )
