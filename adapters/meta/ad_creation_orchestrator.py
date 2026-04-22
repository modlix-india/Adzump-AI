from typing import Optional
from core.models.meta import (
    MetaAdCreationRequest,
    AssembledMetaPayloads,
    ExistingIdsPayload,
    AdCreationStage,
    MetaAdCreationResponse,
)
from core.infrastructure.context import auth_context
from structlog import get_logger
from structlog.contextvars import bind_contextvars, clear_contextvars
from adapters.meta.exceptions import MetaAdCreationError
from agents.meta.meta_payload_service import MetaPayloadAssemblyService
from adapters.meta.meta_ad_executor import MetaAdExecutor
from adapters.meta.client import meta_client
import asyncio

logger = get_logger(__name__)


class MetaAdCreationOrchestrator:
    """Manage the lifecycle of Meta Ad creation, from payload assembly to platform execution."""

    def __init__(
        self,
        executor: MetaAdExecutor,
        existing_ids: ExistingIdsPayload,
    ):
        """Initialize the orchestrator with an executor and existing entity tracking."""
        self.executor = executor
        self.existing_ids = existing_ids
        self.payloads: Optional[AssembledMetaPayloads] = None
        self.current_stage = AdCreationStage.ASSEMBLY

    @staticmethod
    async def create_full_structure(
        meta_request: MetaAdCreationRequest, inspect_payload: bool
    ) -> AssembledMetaPayloads | MetaAdCreationResponse:
        """Factory method to initialize and run the full ad creation lifecycle."""
        meta_executor = MetaAdExecutor(meta_client, meta_request.ad_account_id)

        existing_ids = meta_request.existing_ids or ExistingIdsPayload()

        orchestrator = MetaAdCreationOrchestrator(meta_executor, existing_ids)
        return await orchestrator.execute_creation_lifecycle(
            meta_request, inspect_payload
        )

    async def execute_creation_lifecycle(
        self, meta_request: MetaAdCreationRequest, inspect_payload: bool
    ) -> AssembledMetaPayloads | MetaAdCreationResponse:
        """Orchestrate the full ad creation lifecycle including assembly, concurrent stages, and final linking."""
        # Initialize structural logging context. These variables will be automatically
        # attached to every subsequent log entry for this request thread.
        bind_contextvars(
            client_code=auth_context.client_code,
            ad_account_id=meta_request.ad_account_id,
        )
        try:
            # Idempotency Guard: If the final Ad already exists and we aren't in payload-inspection mode,
            # return the existing IDs immediately to bypass redundant assembly and execution.
            if not inspect_payload and self.existing_ids.ad_id:
                logger.info(
                    "Ad creation already complete, returning existing IDs",
                    ad_id=self.existing_ids.ad_id,
                )
                return MetaAdCreationResponse(ids=self.existing_ids)

            # Phase 1: Assembly
            self.payloads = await MetaPayloadAssemblyService.assemble_meta_payloads(
                meta_request
            )

            if inspect_payload:
                return self.payloads

            self.current_stage = AdCreationStage.CAMPAIGN

            # Phase 2: Concurrent Stages (Campaign/AdSet + Creative)
            logger.info("Executing concurrent ad creation stages")
            await self._execute_concurrent_stages()

            # Phase 3: Final Ad Creation
            self.current_stage = AdCreationStage.AD
            logger.info("Executing final ad linking stage")
            await self._create_final_ad()

            return MetaAdCreationResponse(ids=self.existing_ids)

        except Exception as exc:
            if isinstance(exc, MetaAdCreationError):
                raise

            raise MetaAdCreationError(
                failed_stage=self.current_stage.value,
                existing_ids=self.existing_ids.model_dump(),
                original_exc=exc,
            ) from exc
        finally:
            # Clear contextvars to ensure no data leaks between threads/tasks
            clear_contextvars()

    async def _execute_concurrent_stages(self):
        """Coordinate concurrent creation of the Campaign/AdSet and the Ad Creative."""
        results = await asyncio.gather(
            self._create_campaign_and_adset(),
            self._create_creative(),
            return_exceptions=True,
        )

        failures = [
            (i, res) for i, res in enumerate(results) if isinstance(res, Exception)
        ]

        if failures:
            for i, exc in failures:
                track_name = "Campaign/AdSet" if i == 0 else "Creative"
                logger.error(
                    "Concurrent ad creation track failed",
                    track=track_name,
                    error=str(exc),
                )

            first_index, first_exc = failures[0]
            parallel_stage = (
                AdCreationStage.CREATIVE
                if first_index == 1
                else (
                    AdCreationStage.ADSET
                    if self.existing_ids.campaign_id
                    else AdCreationStage.CAMPAIGN
                )
            )

            raise MetaAdCreationError(
                failed_stage=parallel_stage.value,
                existing_ids=self.existing_ids.model_dump(),
                original_exc=first_exc,
            ) from first_exc

    async def _create_final_ad(self):
        """Link the AdSet and Creative into a single Ad entity."""
        if self.existing_ids.ad_id:
            logger.info(
                "Ad already exists, skipping creation",
                ad_id=self.existing_ids.ad_id,
            )
            return

        if not self.existing_ids.adset_id or not self.existing_ids.creative_id:
            raise ValueError(
                f"Cannot create Ad: missing prerequisites — "
                f"adset_id={self.existing_ids.adset_id}, "
                f"creative_id={self.existing_ids.creative_id}"
            )

        ad_payload = {
            **self.payloads.ad_payload,
            "adset_id": self.existing_ids.adset_id,
            "creative": {"creative_id": self.existing_ids.creative_id},
        }

        self.existing_ids.ad_id = await self.executor.create_entity(
            AdCreationStage.AD, ad_payload
        )

        logger.info(
            "Ad created successfully",
            ad_id=self.existing_ids.ad_id,
        )

    async def _create_campaign_and_adset(self) -> tuple:
        """Handle sequential creation of Campaign and AdSet entities."""
        # Stage 1: Campaign Creation (Handles recovery if ID is already provided)
        campaign_id = self.existing_ids.campaign_id
        if campaign_id:
            logger.info("Using existing campaign", campaign_id=campaign_id)
        else:
            campaign_id = await self.executor.create_entity(
                AdCreationStage.CAMPAIGN, self.payloads.campaign_payload
            )
            logger.info("Campaign created", campaign_id=campaign_id)
            self.existing_ids.campaign_id = campaign_id

        # Stage 2: AdSet Creation (Linked to the parent Campaign)
        adset_id = self.existing_ids.adset_id
        if adset_id:
            logger.info("Using existing adset", adset_id=adset_id)
        else:
            # Use a copy to avoid mutating the core payloads model
            payload = self.payloads.adset_payload.copy()
            payload["campaign_id"] = campaign_id
            adset_id = await self.executor.create_entity(AdCreationStage.ADSET, payload)
            logger.info("Adset created", adset_id=adset_id)
            self.existing_ids.adset_id = adset_id

        return campaign_id, adset_id

    async def _create_creative(self) -> str:
        """Handle creation of the AdCreative entity."""
        creative_id = self.existing_ids.creative_id
        if creative_id:
            logger.info("Using existing creative", creative_id=creative_id)
            return creative_id

        creative_id = await self.executor.create_entity(
            AdCreationStage.CREATIVE, self.payloads.creative_payload
        )
        logger.info("Creative created", creative_id=creative_id)
        self.existing_ids.creative_id = creative_id
        return creative_id
