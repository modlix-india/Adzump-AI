from typing import List, Dict, Optional
import os
import asyncio
import logging
from oserver.services import connection
from third_party.google.services import keywords_service
from services.business_service import BusinessService
from third_party.google.models.keyword_model import KeywordSuggestion, Keyword
from models.business_model import BusinessMetadata
from services.google_kw_update_service import config

logger = logging.getLogger(__name__)


class GoogleAdsDataFetcher:
    """ Fetches data from Google Ads API and business service. """
    
    def __init__(self):
        self.business_service = BusinessService()
    
    async def fetch_existing_campaign_keywords(
        self,
        customer_id: str,
        campaign_id: str,
        login_customer_id: str,
        client_code: str,
        ad_group_id: Optional[str] = None,
        duration: Optional[str] = None,
        include_negatives: bool = False,
        include_metrics: bool = False,
    ) -> List[Keyword]:

        logger.info(f"Fetching keywords for campaign {campaign_id}")
        
        # Get authentication credentials
        google_access_token = connection.fetch_google_api_token_simple(client_code)
        developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
        
        if not developer_token:
            raise ValueError("GOOGLE_ADS_DEVELOPER_TOKEN environment variable is required")
        
        # Fetch keywords from Google Ads API
        response = await keywords_service.fetch_campaign_keywords(
            customer_id=customer_id,
            campaign_id=campaign_id,
            login_customer_id=login_customer_id,
            access_token=google_access_token,
            developer_token=developer_token,
            duration=duration,
            ad_group_id=ad_group_id,
            include_negatives=include_negatives,
            include_metrics=include_metrics
        )
        
        if response.status != "success":
            raise ValueError(f"Failed to fetch keywords: {response.status}")
        
        logger.info(
            f"Fetched {len(response.keywords)} keywords "
            f"using date range: {response.date_range_used}"
        )
        
        return response.keywords
    
    async def fetch_business_context_data(
        self,
        data_object_id: str,
        access_token: str,
        client_code: str
    ) -> Dict:
  
        try:
            # Fetch product details
            product_data = await self.business_service.fetch_product_details(
                data_object_id=data_object_id,
                access_token=access_token,
                client_code=client_code
            )
            
            business_summary = product_data.get('summary')
            business_url = product_data.get('businessUrl')
            
            if not business_summary:
                logger.error(f"No business data for data_object_id: {data_object_id}")
                return self._create_empty_business_context()
            
            # Extract business metadata and features concurrently
            business_metadata, unique_features = await asyncio.gather(
                self.business_service.extract_business_metadata(business_summary, business_url),
                self.business_service.extract_business_unique_features(business_summary),
                return_exceptions=True
            )
            
            # Handle extraction failures
            if isinstance(business_metadata, Exception):
                logger.warning(f"Business metadata extraction failed: {business_metadata}")
                business_metadata = BusinessMetadata()
            
            if isinstance(unique_features, Exception):
                logger.warning(f"Unique features extraction failed: {unique_features}")
                unique_features = []
            
            return {
                "brand_info": business_metadata,
                "unique_features": unique_features,
                "url": business_url,
                "summary": business_summary
            }
        
        except Exception as e:
            logger.exception(f"Error fetching business context: {e}")
            return self._create_empty_business_context()
    
    async def fetch_google_keyword_suggestions(
        self,
        top_performer_keywords: List[Keyword],
        business_context: Dict,
        customer_id: str,
        login_customer_id: str,
        client_code: str,
        location_ids: List[str] = None,
        language_id: int = None
    ) -> List[Dict]:
        logger.info(f"Fetching keyword ideas for {len(top_performer_keywords)} top performers")
        
        # Extract seed keywords
        seed_keyword_texts = [kw.keyword for kw in top_performer_keywords]
        
        # Call Google Ads Keyword Ideas API
        google_keyword_suggestions: List[KeywordSuggestion] = await keywords_service.google_ads_generate_keyword_ideas(
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            access_token=connection.fetch_google_api_token_simple(client_code),
            seed_keywords=seed_keyword_texts,
            location_ids=location_ids or config.DEFAULT_LOCATION_IDS,
            language_id=language_id or config.DEFAULT_LANGUAGE_ID,
            url=business_context.get('url')
        )
        
        if not google_keyword_suggestions:
            logger.warning("No suggestions from Google Keyword Ideas API")
            return []
        
        logger.info(f"Got {len(google_keyword_suggestions)} keyword ideas from Google")
        
        suggestion_dicts = [s.model_dump(mode='json') for s in google_keyword_suggestions]
        
        suggestion_dicts.sort(key=lambda x: x.get('roi_score', 0), reverse=True)
        top_suggestions = suggestion_dicts[:80]
        
        logger.info(f"Pre-filtered to top {len(top_suggestions)} suggestions by ROI score")
                
        return top_suggestions
    
    @staticmethod
    def _create_empty_business_context() -> Dict:
        return {
            "brand_info": BusinessMetadata(),
            "unique_features": [],
            "url": None,
            "summary": None
        }