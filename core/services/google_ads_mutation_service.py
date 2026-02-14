import structlog
from core.models.optimization import (
    MutationResponse,
    CampaignRecommendation,
)
from adapters.google.mutation.operation_build_coordinator import (
    OperationBuildCoordinator,
)
from adapters.google.mutation.mutation_context import MutationContext

from core.services.recommendation_storage import recommendation_storage_service
from core.infrastructure.context import auth_context

logger = structlog.get_logger(__name__)


class GoogleAdsMutationService:
    """Executes Google Ads mutations for campaign recommendations."""

    def __init__(self):
        self.coordinator = OperationBuildCoordinator()

    async def execute_mutation(
        self, campaign: CampaignRecommendation, is_partial: bool = False
    ) -> MutationResponse:
        """Execute mutations for a campaign recommendation and sync results."""
        client_code = auth_context.client_code

        mutation_context = MutationContext(
            account_id=campaign.account_id,
            parent_account_id=campaign.parent_account_id,
            campaign_id=campaign.campaign_id,
            client_code=client_code,
        )

        logger.info("Starting mutation", campaign_id=campaign.campaign_id)
        operations = await self.coordinator.build_campaign_mutations(
            recommendation=campaign, context=mutation_context
        )

        if not operations:
            return MutationResponse(
                success=True,
                message="No operations to execute",
                campaignRecommendation=campaign,
            )

        await self.coordinator.execute_operations(mutation_context, operations)

        # Sync results to storage
        updated_campaign = await self._sync_mutation_to_storage(campaign, is_partial)

        logger.info(
            "Mutation successful",
            campaign_id=campaign.campaign_id,
            ops=len(operations),
        )
        return MutationResponse(
            success=True,
            message=f"Mutation successful: {len(operations)} operations.",
            campaignRecommendation=updated_campaign,
        )

    async def validate_mutation(
        self, campaign: CampaignRecommendation
    ) -> MutationResponse:
        """Build operations and return them for validation (dry-run)."""
        client_code = auth_context.client_code

        mutation_context = MutationContext(
            account_id=campaign.account_id,
            parent_account_id=campaign.parent_account_id,
            campaign_id=campaign.campaign_id,
            client_code=client_code,
        )

        logger.info("Validating mutation", campaign_id=campaign.campaign_id)
        operations = await self.coordinator.build_campaign_mutations(
            recommendation=campaign, context=mutation_context
        )

        return MutationResponse(
            success=True,
            message=f"Validation successful. {len(operations)} operations ready.",
            campaignRecommendation=campaign,
            operations=operations,
        )

    async def _sync_mutation_to_storage(
        self, campaign: CampaignRecommendation, is_partial: bool
    ) -> CampaignRecommendation:
        """Handles database updates for the campaign recommendation."""
        try:
            return await recommendation_storage_service.apply_mutation_results(
                campaign, is_partial
            )
        except Exception as e:
            logger.error(
                "Storage sync failed post-mutation",
                error=str(e),
                campaign_id=campaign.campaign_id,
            )
            return campaign


# Singleton instance for shared use
google_ads_mutation_service = GoogleAdsMutationService()
