from typing import List, Dict, Tuple
import asyncio
import logging
from third_party.google.models.keyword_model import Keyword, UpdateKeywordsStrategyRequest, UpdateKeywordsStrategyResponse
from services.google_kw_update_service.google_kw_fetcher import GoogleAdsDataFetcher
from services.google_kw_update_service.google_kw_classifer import KeywordPerformanceClassifier
from services.google_kw_update_service.google_kw_llm_analyzer import LLMKeywordAnalyzer
from services.google_kw_update_service.google_kw_scorer import MultiFactorKeywordScorer, SemanticSimilarityScorer
from services.google_kw_update_service import config

logger = logging.getLogger(__name__)

class GoogleAdsKeywordUpdateService:
    # Main service orchestrating keyword analysis and update workflow.
    
    def __init__(
        self,
        performance_classifier: KeywordPerformanceClassifier = None,
        semantic_scorer: SemanticSimilarityScorer = None,
        keyword_scorer: MultiFactorKeywordScorer = None,
        data_fetcher: GoogleAdsDataFetcher = None
    ):
        self.performance_classifier = performance_classifier or KeywordPerformanceClassifier()
        self.semantic_scorer = semantic_scorer or SemanticSimilarityScorer()
        self.keyword_scorer = keyword_scorer or MultiFactorKeywordScorer()
        self.llm_analyzer = LLMKeywordAnalyzer(self.keyword_scorer)
        self.data_fetcher = data_fetcher or GoogleAdsDataFetcher()
    
    async def analyze_and_update_campaign_keywords(
        self,
        keyword_update_request: UpdateKeywordsStrategyRequest,
        access_token: str,
        client_code: str,
    ) -> UpdateKeywordsStrategyResponse:
        # Main workflow for analyzing campaign and generating keyword suggestions.

        campaign_id = keyword_update_request.campaign_id
        
        logger.info(f"STARTING KEYWORD UPDATE STRATEGY FOR CAMPAIGN {campaign_id}")

        # Step 1: Fetch initial data concurrently
        all_keywords, business_context = await self._fetch_initial_campaign_data(
            keyword_update_request, access_token, client_code
        )
        
        # Handle no keywords case
        if not all_keywords:
            logger.warning("No keywords found in campaign")
            return UpdateKeywordsStrategyResponse.create_no_keywords(campaign_id, all_keywords)
        
        logger.info(f"Fetched {len(all_keywords)} keywords")
        
        # Step 2: Classify keywords
        logger.info("STEP 2: Classifying keywords as good or poor performers")
        good_keywords, poor_keywords = self.performance_classifier.classify_keywords_by_performance(all_keywords)
        
        # Handle no good keywords case
        if not good_keywords:
            logger.warning("No good keywords found - cannot generate suggestions")
            return UpdateKeywordsStrategyResponse.create_no_good_keywords(
                campaign_id, all_keywords, poor_keywords
            )
        
        # Step 3: Extract top performers
        logger.info("STEP 3: Identifying top performers")
        top_performer_keywords = self.performance_classifier.extract_top_performers(
            good_keywords, 
            top_percentage=config.TOP_PERFORMER_PERCENTAGE
        )
        
        # Step 4: Generate keyword suggestions
        logger.info(f"STEP 4: Generating keyword suggestions")
        keyword_suggestions = await self._generate_and_analyze_keyword_suggestions(
            request=keyword_update_request,
            top_performer_keywords=top_performer_keywords,
            all_existing_keywords=all_keywords,
            business_context=business_context,
            client_code=client_code
        )
        
        logger.info("KEYWORD UPDATE STRATEGY COMPLETE")
        
        return UpdateKeywordsStrategyResponse.create_success(
            campaign_id=campaign_id,
            all_keywords=all_keywords,
            good_keywords=good_keywords,
            poor_keywords=poor_keywords,
            top_performers=top_performer_keywords,
            suggestions=keyword_suggestions
        )
    
    async def _fetch_initial_campaign_data(
        self,
        request: UpdateKeywordsStrategyRequest,
        access_token: str,
        client_code: str
    ) -> Tuple[List[Keyword], Dict]:
        # Fetch keywords and business context concurrently.
        logger.info("Step 1: Fetching keywords and business context concurrently...")
        
        all_keywords, business_context = await asyncio.gather(
            self.data_fetcher.fetch_existing_campaign_keywords(
                customer_id=request.customer_id,
                campaign_id=request.campaign_id,
                login_customer_id=request.login_customer_id,
                client_code=client_code,
                ad_group_id=request.ad_group_id,
                duration=request.duration,
                include_negatives=request.include_negatives,
                include_metrics=request.include_metrics
            ),
            self.data_fetcher.fetch_business_context_data(
                data_object_id=request.data_object_id,
                access_token=access_token,
                client_code=client_code
            ),
            return_exceptions=True
        )
        
        if isinstance(all_keywords, Exception):
            logger.error(f"Failed to fetch keywords: {all_keywords}")
            raise all_keywords
        
        if isinstance(business_context, Exception):
            logger.warning(f"Failed to fetch business context: {business_context}")
            business_context = self.data_fetcher._create_empty_business_context()
        
        return all_keywords, business_context
    
    async def _generate_and_analyze_keyword_suggestions(
        self,
        request: UpdateKeywordsStrategyRequest,
        top_performer_keywords: List[Keyword],
        all_existing_keywords: List[Keyword],
        business_context: Dict,
        client_code: str
    ) -> List[Dict]:
        # Generate keyword suggestions and analyze with LLM.

        if not top_performer_keywords:
            logger.warning("No top performers to generate suggestions from")
            return []

        # Fetch Google keyword suggestions
        google_suggestions_list = await self.data_fetcher.fetch_google_keyword_suggestions(
            top_performer_keywords=top_performer_keywords,
            business_context=business_context,
            customer_id=request.customer_id,
            login_customer_id=request.login_customer_id,
            client_code=client_code,
            location_ids=request.location_ids or config.DEFAULT_LOCATION_IDS,
            language_id=request.language_id or config.DEFAULT_LANGUAGE_ID
        )
        
        if not google_suggestions_list:
            logger.warning("No suggestions from Google Ads API")
            return []
        
        # Calculate semantic similarity scores
        semantic_scores = await self.semantic_scorer.calculate_semantic_similarity_scores(
            suggestion_keywords=google_suggestions_list,
            top_performer_keywords=top_performer_keywords
        )
        
        # Add semantic scores to suggestions
        for suggestion in google_suggestions_list:
            suggestion['semantic_score'] = semantic_scores.get(suggestion['keyword'].lower(), 50.0)
        
        # Analyze with LLM and finalize
        analyzed_suggestions = await self.llm_analyzer.analyze_and_select_keywords(
            suggestion_keywords=google_suggestions_list,
            top_performer_keywords=top_performer_keywords,
            existing_keywords=all_existing_keywords,
            business_context=business_context
        )
        
        return analyzed_suggestions