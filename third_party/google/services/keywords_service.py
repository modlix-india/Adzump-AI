import os
import httpx
import logging
from oserver.services.connection import fetch_google_api_token_simple
import utils.date_utils as date_utils
from third_party.google.models.keyword_model import Keyword


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def fetch_keywords(
    client_code: str,
    customer_id: str,
    login_customer_id: str,
    campaign_id: str,
    duration: str,
) -> list:
    """
    Fetch active keywords and their metrics for a given campaign using a single keyword_view query.
    """
    try:
        # Step 1: Auth setup
        developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
        google_ads_access_token = fetch_google_api_token_simple(client_code=client_code)

        
        if not developer_token or not google_ads_access_token:
            raise ValueError("Missing Google Ads credentials or tokens.")

        endpoint = f"https://googleads.googleapis.com/v20/customers/{customer_id}/googleAds:search"
        headers = {
            "Authorization": f"Bearer {google_ads_access_token}",
            "developer-token": developer_token,
            "login-customer-id": login_customer_id,
            "Content-Type": "application/json",
        }

        duration_clause = date_utils.format_duration_clause(duration)

        # Step 2: Single keyword_view query
        
        keyword_view_query = f"""
        SELECT
          campaign.id, 
          ad_group.id, 
          ad_group_criterion.criterion_id, 
          ad_group_criterion.status,  
          ad_group_criterion.keyword.text,  
          ad_group_criterion.keyword.match_type
        FROM keyword_view
        WHERE
          campaign.id = {campaign_id}
          AND ad_group_criterion.negative = FALSE
          AND segments.date {duration_clause}
          AND ad_group_criterion.status = 'ENABLED'
          AND ad_group.status = 'ENABLED'
          AND campaign.status = 'ENABLED'
        ORDER BY ad_group.id, ad_group_criterion.criterion_id
        """

        # Step 3: Make API request
        async with httpx.AsyncClient() as client:
            response = await client.post(endpoint, headers=headers, json={"query": keyword_view_query})
            if not response.is_success:
                logger.error(f"Keyword fetch failed: {response.text}")
            data = response.json().get("results", [])

        logger.info(f" Keyword View returned {len(data)} rows")

        if not data:
            return []
        
        keywords = [Keyword.from_google_row(row) for row in data]
        logger.info(f"Final keyword count: {len(keywords)}")
        return keywords

    except httpx.RequestError as e:
        logger.error(f"Request failed: {e}")
        return []
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return []
