import asyncio
import base64
from structlog import get_logger
from core.models.meta import MetaAdCreationRequest, CreativePayload, AssembledMetaPayloads
from agents.meta.payload_builders.basic_entity_builders import (
    build_campaign_payload,
    build_ad_payload,
)
from agents.meta.payload_builders.adset_builder.adset_builder import build_adset_payload
from agents.meta.payload_builders.creative_builder import build_creative_payload
from core.infrastructure.http_client import http_request
from adapters.meta.images import MetaAdImageAdapter


logger = get_logger(__name__)


class MetaPayloadAssemblyService:
    """Orchestrate parallel assembly of Meta API payloads from a unified request."""

    @staticmethod
    async def assemble_meta_payloads(
        meta_request: MetaAdCreationRequest,
    ) -> AssembledMetaPayloads:
        """Assemble Campaign, AdSet, Creative, and Ad payloads concurrently."""
        creative_input = meta_request.creative

        # Download image URLs, convert to base64, and upload to Meta to get hashes
        # If creative_id is already present, the creative already exists on Meta and won't be recreated,
        # so we can skip downloading and uploading the images entirely.
        creative_id_exists = (
            meta_request.existing_ids is not None
            and bool(meta_request.existing_ids.creative_id)
        )
        if creative_input.image_urls and not creative_id_exists:
            resolved_hashes = await MetaPayloadAssemblyService._resolve_image_hashes(
                meta_request.ad_account_id, creative_input.image_urls
            )
            creative_input.image_hashes = resolved_hashes


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
    async def _resolve_image_hashes(
        ad_account_id: str, image_urls: list[str]
    ) -> list[str]:
        """Download image URLs, convert to base64, upload to Meta, and return hashes."""
        image_adapter = MetaAdImageAdapter()

        async def _upload_single(url: str) -> str:
            logger.info("Downloading image from URL", url=url)
            response = await http_request("GET", url)
            image_base64 = base64.b64encode(response.content).decode("utf-8")

            logger.info("Uploading image to Meta", url=url)
            upload_result = await image_adapter.upload_image(
                ad_account_id=ad_account_id,
                image_base64=image_base64,
            )
            image_data = next(iter(upload_result["images"].values()))
            image_hash = image_data["hash"]
            logger.info("Image uploaded successfully", url=url, hash=image_hash)
            return image_hash

        return await asyncio.gather(*[_upload_single(url) for url in image_urls])

    @staticmethod
    def _is_dynamic_creative(creative: CreativePayload) -> bool:
        """Return True if any asset (text/headline/image) has multiple variations."""
        images_count = 0
        if creative.image_hashes:
            images_count = len(creative.image_hashes)
        elif creative.image_urls:
            images_count = len(creative.image_urls)

        return (
            len(creative.primary_texts) > 1
            or len(creative.headlines) > 1
            or images_count > 1
            or (creative.descriptions is not None and len(creative.descriptions) > 1)
        )

