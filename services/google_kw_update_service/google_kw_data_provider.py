from typing import List, Dict, Optional
import asyncio
import structlog
import os
from third_party.google.services import keywords_service

# from oserver.services import connection
from services.business_service import BusinessService
from models.business_model import BusinessMetadata
from third_party.google.models.keyword_model import Keyword
from services.google_kw_update_service import config
from core.infrastructure.context import auth_context
from exceptions.custom_exceptions import (
    GoogleAdsException,
    StorageException,
    GoogleAdsAuthException,
)

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
        ad_group_id: Optional[str] = None,
        duration: Optional[str] = None,
        include_negatives: bool = False,
        include_metrics: bool = False,
    ) -> List[Keyword]:
        """Fetch keywords for a campaign from Google Ads API."""
        logger.info("Fetching keywords for campaign", campaign_id=campaign_id)

        # Get credentials via helper
        google_access_token, developer_token = self._get_google_credentials()

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
            raise GoogleAdsException(
                message=f"Failed to fetch keywords: {response.status}"
            )

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
    ) -> Dict:
        """Fetch business context data (product details, metadata, USPs)."""
        try:
            # Fetch product details from Storage
            product_data = await self.business_service.fetch_product_details(
                data_object_id=data_object_id,
                access_token=auth_context.access_token,
                client_code=auth_context.client_code,
                x_forwarded_host=auth_context.x_forwarded_host,
                x_forwarded_port=auth_context.x_forwarded_port,
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
            raise StorageException(message=f"Error fetching business context: {str(e)}")

    async def fetch_google_suggestions(
        self,
        customer_id: str,
        login_customer_id: str,
        seed_keywords: List[str],
        location_ids: List[str] = None,
        language_id: int = None,
        url: str = None,
    ) -> List[Dict]:
        """Fetch keyword ideas from Google Ads API."""
        if not seed_keywords:
            logger.warning("No seed keywords provided for suggestion fetching")
            return []

        # Get credentials via helper
        google_access_token, developer_token = self._get_google_credentials()

        suggestions = await keywords_service.google_ads_generate_keyword_ideas(
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            access_token=google_access_token,
            developer_token=developer_token,
            seed_keywords=seed_keywords,
            location_ids=location_ids or config.DEFAULT_LOCATION_IDS,
            language_id=language_id or config.DEFAULT_LANGUAGE_ID,
            url=url,
        )
        return suggestions

    def _get_google_credentials(self) -> tuple[str, str]:
        """Helper to fetch and validate Google Ads credentials from context and env."""
        # google_access_token = connection.fetch_google_api_token_simple(
        #     auth_context.client_code
        # )
        google_access_token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN")
        developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")

        if not google_access_token or not developer_token:
            missing = []
            if not google_access_token:
                missing.append("Google Ads token")
            if not developer_token:
                missing.append("GOOGLE_ADS_DEVELOPER_TOKEN")
            raise GoogleAdsAuthException(
                message=f"Missing required credentials: {', '.join(missing)}",
                details={"missing": missing},
            )

        return google_access_token, developer_token

    def _create_empty_business_context(self) -> Dict:
        """Create a default empty business context structure."""
        return {
            "brand_info": BusinessMetadata(),
            "unique_features": [],
            "url": None,
            "summary": None,
        }
