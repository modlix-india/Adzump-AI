import asyncio
import structlog
from typing import List, Dict, Any
from adapters.google.mutation.mutation_context import MutationContext
from adapters.google.client import google_ads_client
from core.models.optimization import CampaignRecommendation
from adapters.google.mutation.operation_builders.asset_builders.responsive_search_ad_builder import (
    ResponsiveSearchAdBuilder,
)
from adapters.google.mutation.operation_builders.criterion_targeting_builder import (
    CriterionTargetingBuilder,
)
from adapters.google.mutation.operation_builders.keyword_operation_builder import (
    KeywordOperationBuilder,
)
from adapters.google.mutation.operation_builders.asset_builders.sitelink_operation_builder import (
    SitelinkOperationBuilder,
)

logger = structlog.get_logger(__name__)


class OperationBuildCoordinator:
    def __init__(self):
        self.ad_builder = ResponsiveSearchAdBuilder()
        self.criterion_builder = CriterionTargetingBuilder()
        self.keyword_builder = KeywordOperationBuilder()
        self.sitelink_builder = SitelinkOperationBuilder()
        self.client = google_ads_client

        self._field_builders = {
            "headlines": self.ad_builder.build_headlines_ops,
            "descriptions": self.ad_builder.build_descriptions_ops,
            "keywords": self.keyword_builder.build_keywords_ops,
            "negativeKeywords": self.keyword_builder.build_negative_keywords_ops,
            "age": self.criterion_builder.build_age_ops,
            "gender": self.criterion_builder.build_gender_ops,
            "locationOptimizations": self.criterion_builder.build_location_ops,
            "proximityOptimizations": self.criterion_builder.build_proximity_ops,
            "sitelinks": self.sitelink_builder.build_sitelinks_ops,
        }

    async def build_campaign_mutations(
        self, recommendation: CampaignRecommendation, context: MutationContext
    ) -> List[Dict[str, Any]]:
        all_operations = []

        logger.info(
            "Building campaign mutations",
            campaign_id=recommendation.campaign_id,
        )

        # Create tasks for each recommendation field that has a builder
        tasks = {
            field_name: asyncio.create_task(
                builder(recommendations=recs, context=context)
            )
            for field_name, recs in recommendation.fields
            if recs and (builder := self._field_builders.get(field_name))
        }

        if not tasks:
            return []

        # Concurrent execution with best-effort error isolation
        execution_results = await asyncio.gather(
            *tasks.values(), return_exceptions=True
        )

        for field_name, result in zip(tasks.keys(), execution_results):
            if isinstance(result, Exception):
                logger.error(
                    "Builder failed", field=field_name, error=str(result), exc_info=True
                )
            else:
                all_operations.extend(result)

        logger.info("Operation building complete", count=len(all_operations))
        return all_operations

    async def execute_operations(
        self, context: MutationContext, operations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Execute the actual API call to Google Ads via the client."""
        logger.debug(
            "Executing API call",
            customer_id=context.account_id,
            operations=len(operations),
        )
        return await self.client.mutate(
            customer_id=context.account_id,
            login_customer_id=context.parent_account_id,
            mutate_payload={
                "mutateOperations": operations,
                # Set partialFailure=False for atomic execution (fails entire batch if any op fails)
                "partialFailure": False,
            },
            client_code=context.client_code,
        )
