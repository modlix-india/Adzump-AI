import structlog
from typing import List, Dict, Any
from models.mutation_request_model import MutationRequest, MutationResponse
from adapters.google.client import GoogleAdsClient
from adapters.google.mutation.mutation_validator import MutationValidator
from adapters.google.mutation.mutation_operation_orchestrator import (
    MutationOperationOrchestrator,
)
from adapters.google.mutation.mutation_context import MutationContext

from core.services.recommendation_storage import recommendation_storage_service
from core.infrastructure.context import auth_context

logger = structlog.get_logger(__name__)


class GoogleAdsMutationService:
    """Executes Google Ads mutations for campaign recommendations."""

    def __init__(self):
        self.orchestrator = MutationOperationOrchestrator()
        self.client = GoogleAdsClient()

    async def execute_mutation(self, request: MutationRequest) -> MutationResponse:
        """Execute mutations for a campaign recommendation and sync results."""
        campaign = request.campaignRecommendation
        client_code = auth_context.client_code or getattr(request, "clientCode", "")

        try:
            mutation_context = MutationContext(
                campaign=campaign, client_code=client_code
            )
            MutationValidator.validate_context(mutation_context, campaign.campaign_id)

            logger.info("Starting mutation", campaign_id=campaign.campaign_id)
            operations = await self.orchestrator.build_campaign_mutations(
                mutation_context
            )

            if not operations:
                return MutationResponse(
                    success=True,
                    message="No operations to execute",
                    campaignRecommendation=campaign,
                )

            if request.validateOnly:
                return MutationResponse(
                    success=True,
                    message=f"Validation successful. {len(operations)} operations ready.",
                    campaignRecommendation=campaign,
                    operations=operations,
                )

            await self._execute_google_ads_api_call(mutation_context, operations)

            # Sync results to storage
            updated_campaign = await self._sync_mutation_to_storage(campaign, request)

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

        except Exception as e:
            logger.error(
                "Mutation failed", campaign_id=campaign.campaign_id, error=str(e)
            )
            return MutationResponse(
                success=False,
                message=f"Mutation failed: {str(e)}",
                campaignRecommendation=campaign,
                details=getattr(e, "details", {}),
                errors=[str(e)],
            )

    async def _sync_mutation_to_storage(
        self, campaign: Any, request: MutationRequest
    ) -> Any:
        """Handles database updates for the campaign recommendation."""
        try:
            is_partial = getattr(request, "isPartial", False)
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

    async def _execute_google_ads_api_call(
        self,
        context: MutationContext,
        operations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Execute the actual API call to Google Ads."""
        logger.debug(
            "Executing API call",
            customer_id=context.account_id,
            opeartions=len(operations),
        )
        return await self.client.mutate(
            customer_id=context.account_id,
            login_customer_id=context.parent_account_id,
            mutate_payload={
                "mutateOperations": operations,
                # Set partialFailure=True for best-effort execution (commits valid ops, returns errors for invalid ones)
                # Set partialFailure=False for atomic execution (fails entire batch if any op fails)
                "partialFailure": False,
            },
            client_code=context.client_code,
        )
