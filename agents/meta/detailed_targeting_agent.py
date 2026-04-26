import asyncio
import structlog

from agents.meta.detailed_targeting_executer import MetaTargetingExecutor
from core.models.meta import (
    MetaTargetingSuggestionResult,
    TargetingCategory,
)
from exceptions.custom_exceptions import (
    InternalServerException,
    BaseAppException,
    SessionException,
    BusinessValidationException,
)
from services.business_service import BusinessService
from services.session_manager import sessions

logger = structlog.get_logger(__name__)

# Iterate over Enum members directly to ensure all categories are included
TARGETING_CATEGORIES = list(TargetingCategory)


class DetailedTargetingAgent:
    """
    Entry point for the Meta targeting suggestion agent.

    Resolves business data via BusinessService, then runs the targeting pipeline
    for all three categories in parallel and aggregates the results.
    """

    def __init__(self) -> None:
        """Initialize the detailed targeting agent with business & meta-targeting services."""
        self.business_service = BusinessService()
        self.executor = MetaTargetingExecutor()

    async def generate_detailed_targeting_suggestions(
        self,
        session_id: str,
        ad_account_id: str,
    ) -> MetaTargetingSuggestionResult:
        """
        Generate Meta targeting suggestions by orchestrating LLM analysis
        and Marketing API searches across all targeting categories.
        """
        # Bind context variables for uniform logging across the request lifecycle
        structlog.contextvars.bind_contextvars(
            session_id=session_id,
            ad_account_id=ad_account_id,
        )

        logger.info("meta_detailed_targeting.orchestrator.started")

        try:
            # 1. Session Validation
            if session_id not in sessions:
                raise SessionException("Invalid or expired session.")

            # 2. Business data retrieval
            business_data = await self.business_service.fetch_website_data(session_id)
            business_summary = business_data.final_summary or business_data.summary

            if not business_summary:
                raise BusinessValidationException(
                    "Business summary is missing. Please complete website analysis first."
                )

            # 3. Run targeting pipeline for all categories in parallel
            # We use return_exceptions=True to allow partial success if one category fails
            category_results = await asyncio.gather(
                *[
                    self.executor.run_targeting_pipeline(
                        ad_account_id=ad_account_id,
                        category=category,
                        business_summary=business_summary,
                    )
                    for category in TARGETING_CATEGORIES
                ],
                return_exceptions=True,
            )

            # 4. Results Mapping (Robust to category list changes)
            results_map = {}
            for category, result in zip(TARGETING_CATEGORIES, category_results):
                if isinstance(result, Exception):
                    logger.error(
                        "meta_detailed_targeting.category.failed",
                        category=category.value,
                        error=str(result),
                    )
                    results_map[category.value] = []
                else:
                    results_map[category.value] = result

            # 5. Final Result Construction (Type-safe Enum Mapping)
            final_result = MetaTargetingSuggestionResult(
                interests=results_map.get(TargetingCategory.INTERESTS.value, []),
                demographics=results_map.get(TargetingCategory.DEMOGRAPHICS.value, []),
                behaviors=results_map.get(TargetingCategory.BEHAVIORS.value, []),
            )

            # 6. Global Result Logging & Failure Check
            total_categories = len(TARGETING_CATEGORIES)
            failed_count = sum(1 for r in category_results if isinstance(r, Exception))

            logger.info(
                "meta_detailed_targeting.orchestrator.complete",
                interests_count=len(final_result.interests),
                demographics_count=len(final_result.demographics),
                behaviors_count=len(final_result.behaviors),
                failed_categories=failed_count,
                total_categories=total_categories,
            )

            return final_result

        except BaseAppException:
            # Let our custom exceptions propagate to the global handler
            raise
        except Exception:
            logger.exception("meta_detailed_targeting.orchestrator.error")
            raise InternalServerException(
                "An unexpected error occurred during targeting suggestion generation."
            )
        finally:
            # Clear context variables to prevent leakage to subsequent requests
            structlog.contextvars.clear_contextvars()


# Singleton instance for shared use
detailed_targeting_agent = DetailedTargetingAgent()
