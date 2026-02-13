import asyncio
import structlog
from typing import List, Dict, Any
from adapters.google.mutation.mutation_context import MutationContext
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


class MutationOperationOrchestrator:
    def __init__(self):
        self.ad_builder = ResponsiveSearchAdBuilder()
        self.criterion_builder = CriterionTargetingBuilder()
        self.keyword_builder = KeywordOperationBuilder()
        self.sitelink_builder = SitelinkOperationBuilder()

        self._dispatch = {
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
        self, context: MutationContext
    ) -> List[Dict[str, Any]]:
        all_operations = []
        campaign = context.campaign
        customer_id = context.account_id

        logger.info(
            "Orchestrating mutations",
            customer_id=customer_id,
            campaign_id=campaign.campaign_id,
        )

        # Prepare coroutines for dispatch
        collection_tasks = []
        field_names = []
        for field_name, recommendations in campaign.fields:
            if recommendations and (builder_method := self._dispatch.get(field_name)):
                collection_tasks.append(
                    asyncio.create_task(
                        builder_method(
                            recommendations=recommendations,
                            context=context,
                        )
                    )
                )
                field_names.append(field_name)
            elif recommendations:
                logger.debug("No builder registered for field", field=field_name)

        if not collection_tasks:
            return []

        # Concurrent execution with best-effort error isolation
        execution_results = await asyncio.gather(
            *collection_tasks, return_exceptions=True
        )

        for field_name, result in zip(field_names, execution_results):
            if isinstance(result, Exception):
                logger.error(
                    "Builder failed", field=field_name, error=str(result), exc_info=True
                )
            else:
                all_operations.extend(result)

        logger.info("Orchestration complete", count=len(all_operations))
        return all_operations
