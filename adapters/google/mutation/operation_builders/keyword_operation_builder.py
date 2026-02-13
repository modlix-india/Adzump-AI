from typing import List, Dict, Any
from core.models.optimization import KeywordRecommendation
from adapters.google.mutation.mutation_validator import MutationValidator
from adapters.google.mutation.mutation_context import MutationContext
import structlog

logger = structlog.get_logger(__name__)


class KeywordOperationBuilder:
    def __init__(self):
        self.validator = MutationValidator()

    async def build_keywords_ops(
        self,
        recommendations: List[KeywordRecommendation],
        context: MutationContext,
    ) -> List[Dict[str, Any]]:
        operations = []
        for keyword_recommendation in recommendations:
            if keyword_recommendation.recommendation == "ADD":
                # Validate keyword text and match type
                error = self.validator.validate_keyword(keyword=keyword_recommendation)
                if error:
                    logger.error(
                        "Keyword validation failed",
                        error=error,
                        text=keyword_recommendation.text,
                        match_type=keyword_recommendation.match_type,
                    )
                    continue

                operations.append(
                    {
                        "adGroupCriterionOperation": {
                            "create": {
                                "adGroup": f"customers/{context.account_id}/adGroups/{keyword_recommendation.ad_group_id}",
                                "status": "ENABLED",
                                "keyword": {
                                    "text": keyword_recommendation.text,
                                    "matchType": keyword_recommendation.match_type,
                                },
                            }
                        }
                    }
                )
            elif keyword_recommendation.recommendation == "PAUSE":
                operations.append(
                    {
                        "adGroupCriterionOperation": {
                            "update": {
                                "resourceName": keyword_recommendation.resource_name,
                                "status": "PAUSED",
                            },
                            "updateMask": "status",
                        }
                    }
                )
            elif keyword_recommendation.recommendation == "REMOVE":
                # NOTE: Currently unreachable — KeywordRecommendation only allows "ADD" | "PAUSE".
                # Kept for future support when REMOVE is added to the model.
                operations.append(
                    {
                        "adGroupCriterionOperation": {
                            "remove": keyword_recommendation.resource_name
                        }
                    }
                )

        logger.info("keyword_operations_built", count=len(operations))
        return operations

    async def build_negative_keywords_ops(
        self,
        recommendations: List[KeywordRecommendation],
        context: MutationContext,
    ) -> List[Dict[str, Any]]:
        # TODO: Refactor to reduce duplication with build_keywords_ops
        operations = []
        for keyword_recommendation in recommendations:
            if keyword_recommendation.recommendation == "ADD":
                # Default match type to BROAD for negative keywords if not provided
                if not keyword_recommendation.match_type:
                    keyword_recommendation.match_type = "BROAD"

                # Validate keyword text and match type
                error = self.validator.validate_keyword(keyword=keyword_recommendation)
                if error:
                    logger.error(
                        "Negative keyword validation failed",
                        error=error,
                        text=keyword_recommendation.text,
                        match_type=keyword_recommendation.match_type,
                    )
                    continue

                operations.append(
                    {
                        "adGroupCriterionOperation": {
                            "create": {
                                "adGroup": f"customers/{context.account_id}/adGroups/{keyword_recommendation.ad_group_id}",
                                "status": "ENABLED",
                                "negative": True,
                                "keyword": {
                                    "text": keyword_recommendation.text,
                                    "matchType": keyword_recommendation.match_type,
                                },
                            }
                        }
                    }
                )
            elif keyword_recommendation.recommendation == "REMOVE":
                # NOTE: Currently unreachable — KeywordRecommendation only allows "ADD" | "PAUSE".
                # Kept for future support when REMOVE is added to the model.
                operations.append(
                    {
                        "adGroupCriterionOperation": {
                            "remove": keyword_recommendation.resource_name
                        }
                    }
                )

        logger.info("negative_keyword_operations_built", count=len(operations))
        return operations
