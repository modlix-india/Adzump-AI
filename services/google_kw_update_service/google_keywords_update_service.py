from typing import List, Dict, Tuple
import asyncio
import structlog
from third_party.google.models.keyword_model import (
    Keyword,
    UpdateKeywordsStrategyRequest,
    UpdateKeywordsStrategyResponse,
)
from services.google_kw_update_service.google_kw_data_provider import (
    KeywordDataProvider,
)
from services.google_kw_update_service.google_kw_classifer import (
    KeywordPerformanceClassifier,
)
from services.google_kw_update_service.google_kw_llm_analyzer import LLMKeywordAnalyzer
from services.google_kw_update_service.google_kw_scorer import (
    MultiFactorKeywordScorer,
    SemanticSimilarityScorer,
)
from services.google_kw_update_service import config

logger = structlog.get_logger(__name__)


class GoogleAdsKeywordUpdateService:
    # Main service orchestrating keyword analysis and update workflow.

    def __init__(
        self,
        performance_classifier: KeywordPerformanceClassifier = None,
        semantic_scorer: SemanticSimilarityScorer = None,
        keyword_scorer: MultiFactorKeywordScorer = None,
        llm_analyzer: LLMKeywordAnalyzer = None,
        data_provider: KeywordDataProvider = None,
    ):
        self.performance_classifier = (
            performance_classifier or KeywordPerformanceClassifier()
        )
        self.semantic_scorer = semantic_scorer or SemanticSimilarityScorer()
        self.keyword_scorer = keyword_scorer or MultiFactorKeywordScorer()
        self.llm_analyzer = llm_analyzer or LLMKeywordAnalyzer(self.keyword_scorer)
        self.data_provider = data_provider or KeywordDataProvider()

    async def analyze_and_update_campaign_keywords(
        self,
        keyword_update_request: UpdateKeywordsStrategyRequest,
        storage_access_token: str,
        client_code: str,
        x_forwarded_host: str = None,
        x_forwarded_port: str = None,
    ) -> UpdateKeywordsStrategyResponse:
        # Extract identifiers early for error context
        campaign_id = keyword_update_request.campaign_id
        customer_id = keyword_update_request.customer_id
        login_customer_id = keyword_update_request.login_customer_id

        try:
            logger.info(
                "Starting keyword update strategy",
                campaign_id=campaign_id,
                customer_id=customer_id,
            )

            # Fetch initial data concurrently
            all_keywords, business_context = await self._fetch_initial_campaign_data(
                request=keyword_update_request,
                customer_id=customer_id,
                login_customer_id=login_customer_id,
                storage_access_token=storage_access_token,
                client_code=client_code,
                x_forwarded_host=x_forwarded_host,
                x_forwarded_port=x_forwarded_port,
            )

            # Handle no keywords case
            if not all_keywords:
                logger.warning("No keywords found in campaign", campaign_id=campaign_id)
                return UpdateKeywordsStrategyResponse.create_no_keywords(
                    campaign_id, all_keywords
                )

            logger.info(
                "Fetched keywords", count=len(all_keywords), campaign_id=campaign_id
            )

            # Classify keywords
            logger.info("Classifying keywords as good or poor performers")
            good_keywords, poor_keywords = (
                self.performance_classifier.classify_keywords_by_performance(
                    all_keywords
                )
            )

            # Handle no good keywords case
            if not good_keywords:
                logger.warning("No good keywords found - cannot generate suggestions")
                return UpdateKeywordsStrategyResponse.create_no_good_keywords(
                    campaign_id, all_keywords, poor_keywords
                )

            # Extract top performers
            logger.info("Identifying top performers")
            top_performer_keywords = self.performance_classifier.extract_top_performers(
                good_keywords, top_percentage=config.TOP_PERFORMER_PERCENTAGE
            )

            # Generate keyword suggestions
            logger.info("Generating keyword suggestions")
            keyword_suggestions = await self._generate_and_analyze_keyword_suggestions(
                request=keyword_update_request,
                customer_id=customer_id,
                login_customer_id=login_customer_id,
                top_performer_keywords=top_performer_keywords,
                all_existing_keywords=all_keywords,
                business_context=business_context,
                client_code=client_code,
            )

            logger.info("KEYWORD UPDATE STRATEGY COMPLETE")

            return UpdateKeywordsStrategyResponse.create_success(
                campaign_id=campaign_id,
                all_keywords=all_keywords,
                good_keywords=good_keywords,
                poor_keywords=poor_keywords,
                top_performers=top_performer_keywords,
                suggestions=keyword_suggestions,
            )

        except Exception as e:
            logger.exception(
                "keyword_update_strategy_failed",
                campaign_id=campaign_id,
                error=str(e),
            )
            return UpdateKeywordsStrategyResponse.create_error(str(e), campaign_id)

    async def _fetch_initial_campaign_data(
        self,
        request: UpdateKeywordsStrategyRequest,
        customer_id: str,
        login_customer_id: str,
        storage_access_token: str,
        client_code: str,
        x_forwarded_host: str = None,
        x_forwarded_port: str = None,
    ) -> Tuple[List[Keyword], Dict]:
        # Fetch keywords and business context concurrently.
        logger.info("Fetching keywords and business context concurrently...")

        all_keywords, business_context = await asyncio.gather(
            self.data_provider.fetch_existing_campaign_keywords(
                customer_id=customer_id,
                campaign_id=request.campaign_id,
                login_customer_id=login_customer_id,
                client_code=client_code,
                ad_group_id=request.ad_group_id,
                duration=request.duration,
                include_negatives=request.include_negatives,
                include_metrics=request.include_metrics,
            ),
            self.data_provider.fetch_business_context_data(
                data_object_id=request.data_object_id,
                access_token=storage_access_token,
                client_code=client_code,
                x_forwarded_host=x_forwarded_host,
                x_forwarded_port=x_forwarded_port,
            ),
            return_exceptions=True,
        )

        if isinstance(all_keywords, Exception):
            logger.error(f"Failed to fetch keywords: {all_keywords}")
            raise all_keywords

        if isinstance(business_context, Exception):
            logger.warning(f"Failed to fetch business context: {business_context}")
            business_context = self.data_provider._create_empty_business_context()

        return all_keywords, business_context

    async def _generate_and_analyze_keyword_suggestions(
        self,
        request: UpdateKeywordsStrategyRequest,
        customer_id: str,
        login_customer_id: str,
        top_performer_keywords: List[Keyword],
        all_existing_keywords: List[Keyword],
        business_context: Dict,
        client_code: str,
    ) -> List[Dict]:
        # Generate keyword suggestions and analyze with LLM.

        if not top_performer_keywords:
            logger.warning("No top performers to generate suggestions from")
            return []

        # Fetch Google keyword suggestions
        google_suggestions_list = await self.data_provider.fetch_google_suggestions(
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            client_code=client_code,
            seed_keywords=[kw.keyword for kw in top_performer_keywords],
            location_ids=request.location_ids or config.DEFAULT_LOCATION_IDS,
            language_id=request.language_id or config.DEFAULT_LANGUAGE_ID,
            url=business_context.get("url"),
        )

        if not google_suggestions_list:
            logger.warning("No suggestions from Google Ads API")
            return []

        # Calculate semantic similarity scores
        semantic_scores = (
            await self.semantic_scorer.calculate_semantic_similarity_scores(
                suggestion_keywords=google_suggestions_list,
                top_performer_keywords=top_performer_keywords,
            )
        )

        # Add semantic scores to suggestions
        for suggestion in google_suggestions_list:
            suggestion["semantic_score"] = semantic_scores.get(
                suggestion["keyword"].lower(), 50.0
            )

        # Analyze with LLM and finalize
        analyzed_suggestions = await self.llm_analyzer.analyze_and_select_keywords(
            suggestion_keywords=google_suggestions_list,
            top_performer_keywords=top_performer_keywords,
            existing_keywords=all_existing_keywords,
            business_context=business_context,
        )

        return analyzed_suggestions
