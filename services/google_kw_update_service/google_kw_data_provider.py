from typing import List, Dict, Optional
import asyncio
import structlog
import os
from third_party.google.services import keywords_service
from oserver.services import connection
from services.business_service import BusinessService
from models.business_model import BusinessMetadata
from third_party.google.models.keyword_model import Keyword
from services.google_kw_update_service import config

logger = structlog.get_logger(__name__)


class KeywordDataProvider:
    """Consolidated data provider for Google Ads and Business context data."""

    def __init__(self, business_service: BusinessService = None):
        self.business_service = business_service or BusinessService()

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
        """Fetch keywords for a campaign from Google Ads API."""
        logger.info("Fetching keywords for campaign", campaign_id=campaign_id)

        # Get authentication credentials
        google_access_token = connection.fetch_google_api_token_simple(client_code)
        developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")

        if not developer_token:
            raise ValueError(
                "GOOGLE_ADS_DEVELOPER_TOKEN environment variable is required"
            )

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
            include_metrics=include_metrics,
        )

        if response.status != "success":
            raise ValueError(f"Failed to fetch keywords: {response.status}")

        logger.info(
            "Fetched keywords",
            count=len(response.keywords),
            date_range=response.date_range_used,
            campaign_id=campaign_id,
        )

        return response.keywords

    async def fetch_business_context_data(
        self,
        data_object_id: str,
        access_token: str,
        client_code: str,
        x_forwarded_host: str = None,
        x_forwarded_port: str = None,
    ) -> Dict:
        """Fetch business context data (product details, metadata, USPs)."""
        try:
            # Fetch product details from Storage
            product_data = await self.business_service.fetch_product_details(
                data_object_id=data_object_id,
                access_token=access_token,
                client_code=client_code,
                x_forwarded_host=x_forwarded_host,
                x_forwarded_port=x_forwarded_port,
            )

            business_summary = product_data.get("finalSummary", "")
            business_url = product_data.get("businessUrl", "")

            if not business_summary:
                logger.error(
                    "No business summary found in product data",
                    data_object_id=data_object_id,
                )
                return self._create_empty_business_context()

            # Extract business metadata and features concurrently via LLM
            business_metadata, unique_features = await asyncio.gather(
                self.business_service.extract_business_metadata(
                    business_summary, business_url
                ),
                self.business_service.extract_business_unique_features(
                    business_summary
                ),
                return_exceptions=True,
            )

            # Handle extraction failures with defaults
            if isinstance(business_metadata, Exception):
                logger.warning(
                    "Business metadata extraction failed", error=str(business_metadata)
                )
                business_metadata = BusinessMetadata()

            if isinstance(unique_features, Exception):
                logger.warning(
                    "Unique features extraction failed", error=str(unique_features)
                )
                unique_features = []

            return {
                "brand_info": business_metadata,
                "unique_features": unique_features,
                "url": business_url,
                "summary": business_summary,
            }

        except Exception as e:
            logger.exception("Error fetching business context", error=str(e))
            return self._create_empty_business_context()

    async def fetch_google_suggestions(
        self,
        customer_id: str,
        login_customer_id: str,
        client_code: str,
        seed_keywords: List[str],
        location_ids: List[str] = None,
        language_id: int = None,
        url: str = None,
    ) -> List[Dict]:
        """Fetch keyword ideas from Google Ads API."""
        google_access_token = connection.fetch_google_api_token_simple(client_code)

        suggestions = await keywords_service.google_ads_generate_keyword_ideas(
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            access_token=google_access_token,
            seed_keywords=seed_keywords,
            location_ids=location_ids or config.DEFAULT_LOCATION_IDS,
            language_id=language_id or config.DEFAULT_LANGUAGE_ID,
            url=url,
        )
        return suggestions

    def _create_empty_business_context(self) -> Dict:
        """Create a default empty business context structure."""
        return {
            "brand_info": BusinessMetadata(),
            "unique_features": [],
            "url": None,
            "summary": None,
        }
