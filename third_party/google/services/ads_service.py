import os
import httpx
from structlog import get_logger  # type: ignore

from oserver.models.storage_request_model import StorageFilter, StorageReadRequest
from oserver.services.connection import fetch_google_api_token_simple
from oserver.services.storage_service import StorageService

logger = get_logger(__name__)


async def fetch_ads(
    client_code: str,
    customer_id: str,
    login_customer_id: str,
    campaign_id: str,
    access_token: str,
) -> list:
    """
    Fetch ads (currently final URLs) for a given campaign from Google Ads API.
    """
    try:
        developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
        # google_ads_access_token = fetch_google_api_token_simple(client_code=client_code)
        google_ads_access_token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN")

        if not developer_token or not google_ads_access_token:
            raise ValueError("Missing Google Ads credentials or tokens.")

        endpoint = f"https://googleads.googleapis.com/v20/customers/{customer_id}/googleAds:search"
        headers = {
            "Authorization": f"Bearer {google_ads_access_token}",
            "developer-token": developer_token,
            "login-customer-id": login_customer_id,
            "Content-Type": "application/json",
        }

        ad_query = f"""
        SELECT
          campaign.id,
          campaign.name,
          customer.id,
          ad_group.id,
          ad_group_ad.ad.id,
          ad_group_ad.ad.name,
          ad_group_ad.ad.final_urls,
          ad_group_ad.status
        FROM ad_group_ad
        WHERE
          campaign.id = {campaign_id}
          AND ad_group_ad.status = 'ENABLED'
          AND ad_group.status = 'ENABLED'
          AND campaign.status = 'ENABLED'
        ORDER BY campaign.id
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint, headers=headers, json={"query": ad_query}
            )
            if not response.is_success:
                logger.error(
                    "[AdsService] Ad fetch failed", error_body=response.text[:500]
                )
                return []

            data = response.json().get("results", [])

        logger.info("[AdsService] Ad Group Ad View response", row_count=len(data))

        if not data:
            return []

        ads_with_summary = []
        for row in data:
            ad_info = row.get("adGroupAd", {}).get("ad", {})
            final_urls = ad_info.get("finalUrls", [])

            ad_obj = {
                "ad_id": ad_info.get("id"),
                "final_urls": final_urls,
                "status": row.get("adGroupAd", {}).get("status"),
                "summaries": [],
            }

            final_url = final_urls[0].rstrip("/")
            storage_service = StorageService(
                access_token=access_token, client_code=client_code
            )
            read_request = StorageReadRequest(
                storageName="AISuggestedData",
                appCode="marketingai",
                clientCode=client_code,
                filter=StorageFilter(field="businessUrl", value=final_url),
            )
            product_summary = await storage_service.read_page_storage(read_request)

            summary = ""

            try:
                summary = product_summary.result[0]["result"]["result"]["content"][
                    0
                ].get("finalSummary", "")
                product_id = product_summary.result[0]["result"]["result"]["content"][
                    0
                ].get("_id", "")

            except (AttributeError, IndexError, KeyError, TypeError):
                summary = ""

            if not summary:
                raise Exception("Missing 'summary' or 'businessUrl' in product data")

            ad_obj["summaries"].append(summary)
            ad_obj["product_id"] = product_id
            ad_obj["campaign_name"] = row.get("campaign", {}).get("name")
            ad_obj["customer_id"] = row.get("customer", {}).get("id")

            ads_with_summary.append(ad_obj)

        logger.info("[AdsService] Final ads processed", count=len(ads_with_summary))
        return ads_with_summary

    except httpx.RequestError as e:
        logger.error("[AdsService] Request failed", error=str(e))
        return []
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return []
