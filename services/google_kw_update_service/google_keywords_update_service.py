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
from services.google_kw_update_service.google_kw_seed_expander import (
    EnhancedSeedExpander,
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
        seed_expander: EnhancedSeedExpander = None,
    ):
        self.performance_classifier = (
            performance_classifier or KeywordPerformanceClassifier()
        )
        self.semantic_scorer = semantic_scorer or SemanticSimilarityScorer()
        self.keyword_scorer = keyword_scorer or MultiFactorKeywordScorer()
        self.llm_analyzer = llm_analyzer or LLMKeywordAnalyzer(self.keyword_scorer)
        self.data_provider = data_provider or KeywordDataProvider()
        self.seed_expander = seed_expander or EnhancedSeedExpander()

    async def analyze_and_update_campaign_keywords(
        self,
        keyword_update_request: UpdateKeywordsStrategyRequest,
    ) -> UpdateKeywordsStrategyResponse:
        # Extract identifiers early for error context
        campaign_id = keyword_update_request.campaign_id
        customer_id = keyword_update_request.customer_id
        login_customer_id = keyword_update_request.login_customer_id

        # Fetch initial data concurrently
        all_keywords, business_context = await self._fetch_initial_campaign_data(
            request=keyword_update_request,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
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
            self.performance_classifier.classify_keywords_by_performance(all_keywords)
        )

        # Handle no good keywords case
        if not good_keywords:
            logger.warning("No good keywords found - cannot generate suggestions")
            return UpdateKeywordsStrategyResponse.create_no_good_keywords(
                campaign_id, all_keywords, poor_keywords
            )

        # Determine seed keywords (with optional enhancement)
        if config.ENABLE_ENHANCED_SEED_EXPANSION:
            logger.info("Enhanced seed expansion enabled")
            seed_keywords_list = await self.seed_expander.expand_seed_keywords(
                good_keywords=good_keywords,
                business_context=business_context,
            )
        else:
            logger.info("Using good keywords directly as seeds")
            seed_keywords_list = [kw.keyword for kw in good_keywords]

        logger.info(
            f"Total seeds for Google Ads API: {len(seed_keywords_list)}",
            enhanced_mode=config.ENABLE_ENHANCED_SEED_EXPANSION,
        )

        # Still extract top performers for response (user wants to see the best ones)
        top_performer_keywords = self.performance_classifier.extract_top_performers(
            good_keywords, top_percentage=config.TOP_PERFORMER_PERCENTAGE
        )

        # Generate keyword suggestions using seed keywords
        logger.info(
            f"Generating keyword suggestions from {len(seed_keywords_list)} seed keywords"
        )
        keyword_suggestions = await self._generate_and_analyze_keyword_suggestions(
            request=keyword_update_request,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            seed_keywords_list=seed_keywords_list,  # Using expanded or direct seeds
            anchor_keywords=good_keywords,  # Use all good keywords for better semantic scoring
            all_existing_keywords=all_keywords,
            business_context=business_context,
        )

        logger.info(
            "KEYWORD UPDATE STRATEGY COMPLETE",
            campaign_id=campaign_id,
            good_count=len(good_keywords),
            suggestions_count=len(keyword_suggestions),
        )

        return UpdateKeywordsStrategyResponse.create_success(
            campaign_id=campaign_id,
            all_keywords=all_keywords,
            good_keywords=good_keywords,
            poor_keywords=poor_keywords,
            top_performers=top_performer_keywords,
            suggestions=keyword_suggestions,
        )

    async def _fetch_initial_campaign_data(
        self,
        request: UpdateKeywordsStrategyRequest,
        customer_id: str,
        login_customer_id: str,
    ) -> Tuple[List[Keyword], Dict]:
        # Fetch keywords and business context concurrently.
        logger.info("Fetching keywords and business context concurrently...")

        all_keywords, business_context = await asyncio.gather(
            self.data_provider.fetch_existing_campaign_keywords(
                customer_id=customer_id,
                campaign_id=request.campaign_id,
                login_customer_id=login_customer_id,
                ad_group_id=request.ad_group_id,
                duration=request.duration,
                include_negatives=request.include_negatives,
                include_metrics=request.include_metrics,
            ),
            self.data_provider.fetch_business_context_data(
                data_object_id=request.data_object_id,
            ),
            return_exceptions=True,
        )

        if isinstance(all_keywords, Exception):
            logger.error(f"Failed to fetch keywords: {all_keywords}")
            raise all_keywords

        if isinstance(business_context, Exception):
            logger.warning(f"Failed to fetch business context: {business_context}")
            raise business_context

        return all_keywords, business_context

    async def _generate_and_analyze_keyword_suggestions(
        self,
        request: UpdateKeywordsStrategyRequest,
        customer_id: str,
        login_customer_id: str,
        seed_keywords_list: List[str],  # Expanded or direct seed keywords
        anchor_keywords: List[Keyword],  # For semantic scoring
        all_existing_keywords: List[Keyword],
        business_context: Dict,
    ) -> List[Dict]:
        """Generate keyword suggestions and analyze with LLM."""

        if not seed_keywords_list:
            logger.warning("No seed keywords to generate suggestions from")
            return []

        # Fetch Google keyword suggestions using seed keywords
        google_suggestions_list = await self.data_provider.fetch_google_suggestions(
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            seed_keywords=seed_keywords_list,  # Using expanded seeds
            location_ids=request.location_ids or config.DEFAULT_LOCATION_IDS,
            language_id=request.language_id or config.DEFAULT_LANGUAGE_ID,
            url=business_context.get("url"),
        )

        if not google_suggestions_list:
            logger.warning("No suggestions from Google Ads API")
            return []

        # Calculate semantic similarity scores using all anchor keywords
        semantic_scores = (
            await self.semantic_scorer.calculate_semantic_similarity_scores(
                suggestion_keywords=google_suggestions_list,
                anchor_keywords=anchor_keywords,
            )
        )

        # Add semantic scores to suggestions
        for suggestion in google_suggestions_list:
            score = semantic_scores.get(suggestion.keyword.lower(), 50.0)
            suggestion.semantic_score = score

        # Analyze with LLM and finalize
        analyzed_suggestions = await self.llm_analyzer.analyze_and_select_keywords(
            suggestion_keywords=google_suggestions_list,
            anchor_keywords=anchor_keywords,
            existing_keywords=all_existing_keywords,
            business_context=business_context,
        )

        return analyzed_suggestions
