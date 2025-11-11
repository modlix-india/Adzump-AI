import os
import httpx
import logging

from oserver.models.storage_request_model import StorageReadRequest
from oserver.services.connection import fetch_google_api_token_simple
from oserver.services.storage_service import read_storage_page

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def fetch_ads(
    client_code: str,
    customer_id: str,
    login_customer_id: str,
    campaign_id: str,
    access_token:str
) -> list:
    """
    Fetch ads (currently final URLs) for a given campaign from Google Ads API.
    """
    try:

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


        ad_query = f"""
        SELECT
          campaign.id,
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
            response = await client.post(endpoint, headers=headers, json={"query": ad_query})
            if not response.is_success:
                logger.error(f"Ad fetch failed: {response.text}")
                return []

            data = response.json().get("results", [])

        logger.info(f"Ad Group Ad View returned {len(data)} rows")

        if not data:
            return []

        ads_with_summary = []
        for row in data:
            ad_info = row.get("adGroupAd", {}).get("ad", {})
            final_urls = ad_info.get("finalUrls", [])

            ad_obj = {
                "ad_id": ad_info.get("id"),
                "name": ad_info.get("name"),
                "final_urls": final_urls,
                "status": row.get("adGroupAd", {}).get("status"),
                "summaries": [],
            }

            for url in final_urls:
                final_url = url.rstrip('/') 
                payload = StorageReadRequest(
                storageName="AISuggestedData",
                clientCode=client_code,
                appCode="marketingai",
                dataObjectId=final_url,
                eager=False,
                eagerFields=[],
                filter={
                     "field":"businessUrl",
                    "value":final_url
                }
                )
                product_summary = await read_storage_page(payload, access_token ,client_code)
                summary = ""
                try:
                    summary = product_summary.result[0]["result"]["result"]["content"][0].get("summary", "")
                except (AttributeError, IndexError, KeyError, TypeError):
                    summary = ""

                if not summary:
                    raise Exception(status_code=400, detail="Missing 'summary' or 'businessUrl' in product data")
                if summary:
                    ad_obj["summaries"].append(summary)
            

            
            ads_with_summary.append(ad_obj)

        logger.info(f"Final ads count: {len(ads_with_summary)}")
        return ads_with_summary

    except httpx.RequestError as e:
        logger.error(f"Request failed: {e}")
        return []
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return []