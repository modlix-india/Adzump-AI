
import os
from typing import Any, Dict
import httpx

from oserver.services.connection import fetch_google_api_token_simple


class GoogleAdsClientError(Exception):
    pass



async def post_mutate_operations(
    customer_id: str,
    login_customer_id: str,
    mutate_payload: Dict[str, Any],
    client_code: str,
    api_version: str = "v20",
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """
    Post the provided mutate payload to Google Ads API and return JSON response.
    """
    developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
    access_token =  fetch_google_api_token_simple(client_code)
    # access_token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN")
    if not developer_token or not access_token:
        raise GoogleAdsClientError("Missing Google Ads credentials or tokens.")

    

    url = f"https://googleads.googleapis.com/{api_version}/customers/{customer_id}/googleAds:mutate"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Developer-Token": developer_token,
        # login-customer-id header is required when making calls on behalf of manager account or when specified
        "login-customer-id": login_customer_id,
    }

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.post(url, json=mutate_payload, headers=headers)

    try:
        data = resp.json()
    except ValueError:
        # Non-JSON response
        data = {"raw_text": resp.text}

    if resp.status_code != 200:
        # bubble up response and status for the caller to handle/log
        raise GoogleAdsClientError(f"Google Ads API error: {resp.status_code} - {data}")

    return data
