import asyncio
from structlog import get_logger

from agents.meta.detailed_targeting_executer import MetaTargetingExecutor
from core.models.meta import (
    MetaTargetingSuggestionResult,
    TargetingCategory,
)
from exceptions.custom_exceptions import BusinessValidationException
from oserver.models.storage_request_model import StorageFilter, StorageReadRequest
from oserver.services.storage_service import StorageService
from services.session_manager import get_website_url
from utils.helpers import normalize_url

logger = get_logger(__name__)

TARGETING_CATEGORIES = [
    TargetingCategory.INTERESTS,
    TargetingCategory.DEMOGRAPHICS,
    TargetingCategory.BEHAVIORS,
]


class DetailedTargetingAgent:
    """
    Entry point for the Meta targeting suggestion agent.

    Resolves the business URL from the session, reads the stored summary
    directly from StorageService, then runs the targeting pipeline for
    all three categories in parallel and aggregates the results.
    """

    def __init__(self) -> None:
        self.storage_service = StorageService()

    async def generate_detailed_targeting_suggestions(
        self,
        session_id: str,
        ad_account_id: str,
    ) -> MetaTargetingSuggestionResult:

        business_summary = await self._fetch_business_summary(session_id)

        executor = MetaTargetingExecutor(ad_account_id=ad_account_id)

        logger.info(
            "meta_targeting.orchestrator_started",
            session_id=session_id,
            ad_account_id=ad_account_id,
            categories=TARGETING_CATEGORIES,
        )

        category_results = await asyncio.gather(
            *[
                executor.run_targeting_pipeline(
                    category=category,
                    business_summary=business_summary,
                )
                for category in TARGETING_CATEGORIES
            ],
            return_exceptions=False,
        )

        interests, demographics, behaviours = category_results

        logger.info(
            "meta_targeting.orchestrator_complete",
            session_id=session_id,
            interests_count=len(interests),
            demographics_count=len(demographics),
            behaviours_count=len(behaviours),
        )

        return MetaTargetingSuggestionResult(
            interests=interests,
            demographics=demographics,
            behaviours=behaviours,
        )

    # Internal helpers

    async def _fetch_business_summary(self, session_id: str) -> str:

        website_url = normalize_url(get_website_url(session_id))

        read_request = StorageReadRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            clientCode=self.storage_service.client_code,
            filter=StorageFilter(field="businessUrl", value=website_url),
        )

        response = await self.storage_service.read_page_storage(read_request)

        if response.success and response.content:
            record = response.content[-1]
            summary = record.get("finalSummary") or record.get("summary")
            if summary:
                logger.info("meta_targeting.business_summary_found")
                return summary

        raise BusinessValidationException(
            "Missing business summary for session. Please complete website analysis first."
        )


meta_detailed_targeting_agent = DetailedTargetingAgent()
