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
                logger.info(
                    "Built keyword ADD operation", text=keyword_recommendation.text
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
                logger.info(
                    "Built keyword PAUSE operation",
                    resource=keyword_recommendation.resource_name,
                )
            elif keyword_recommendation.recommendation == "REMOVE":
                operations.append(
                    {
                        "adGroupCriterionOperation": {
                            "remove": keyword_recommendation.resource_name
                        }
                    }
                )
                logger.info(
                    "Built keyword REMOVE operation",
                    resource=keyword_recommendation.resource_name,
                )
        return operations

    async def build_negative_keywords_ops(
        self,
        recommendations: List[KeywordRecommendation],
        context: MutationContext,
    ) -> List[Dict[str, Any]]:
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
                logger.info(
                    "Built negative keyword ADD operation",
                    text=keyword_recommendation.text,
                )
            elif keyword_recommendation.recommendation == "REMOVE":
                operations.append(
                    {
                        "adGroupCriterionOperation": {
                            "remove": keyword_recommendation.resource_name
                        }
                    }
                )
                logger.info(
                    "Built negative keyword REMOVE operation",
                    resource=keyword_recommendation.resource_name,
                )
        return operations
