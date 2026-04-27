import asyncio
from functools import cached_property

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
    StorageException,
)
from core.infrastructure.context import auth_context
from utils.helpers import normalize_url
from services.business_service import BusinessService
from services.session_manager import sessions, get_website_url
from oserver.models.storage_request_model import StorageReadRequest, StorageFilter
from oserver.services.storage_service import StorageService

logger = structlog.get_logger(__name__)

# Immutable list of categories to iterate over during parallel execution
TARGETING_CATEGORIES = (
    TargetingCategory.INTERESTS,
    TargetingCategory.DEMOGRAPHICS,
    TargetingCategory.BEHAVIORS,
)


class DetailedTargetingAgent:
    """
    Entry point for the Meta targeting suggestion agent.

    Resolves business data via BusinessService, then runs the targeting pipeline
    for all three categories in parallel and aggregates the results.
    """

    @cached_property
    def business_service(self) -> BusinessService:
        """Return lazily-initialized BusinessService instance."""
        return BusinessService()

    @cached_property
    def executor(self) -> MetaTargetingExecutor:
        """Return lazily-initialized MetaTargetingExecutor instance."""
        return MetaTargetingExecutor()

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

            # 2. Fetch business context (Summary of the website) from cache only
            business_summary = await self._get_business_summary(session_id)

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

    async def _get_business_summary(self, session_id: str) -> str:
        """Retrieve the business summary from storage for the current session's website URL."""
        website_url = normalize_url(get_website_url(session_id))
        storage_service = StorageService(
            access_token=auth_context.access_token,
            client_code=auth_context.client_code,
            x_forwarded_host=auth_context.x_forwarded_host,
            x_forwarded_port=auth_context.x_forwarded_port,
        )
        read_request = StorageReadRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            clientCode=auth_context.client_code,
            filter=StorageFilter(field="businessUrl", value=website_url),
        )
        response = await storage_service.read_page_storage(read_request)

        if not response.success:
            raise StorageException(
                message="Failed to retrieve business profile from storage.",
                details={
                    "website_url": website_url,
                    "storage_error": response.error,
                    "storage_name": "AISuggestedData",
                },
            )

        if response.content:
            record = response.content[-1]
            summary = record.get("finalSummary") or record.get("summary")
            if summary:
                return summary

        raise BusinessValidationException(
            message="No business profile found. Please perform a website analysis to generate a summary before requesting targeting suggestions.",
            details={
                "website_url": website_url,
                "storage_name": "AISuggestedData",
                "lookup_field": "businessUrl",
            },
        )


# Singleton instance for shared use
detailed_targeting_agent = DetailedTargetingAgent()
