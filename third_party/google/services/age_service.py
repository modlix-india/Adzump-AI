# TODO: Remove this file - replaced by adapters/google/optimization/age.py
from fastapi import HTTPException
import httpx
import os

from utils.date_utils import format_duration_clause


# ---------------------- Fetch Campaign Metrics ----------------------
async def fetch_age_metrics(
    customer_id: str,
    login_customer_id: str,
    access_token: str,
    campaign_id: str,
    duration: str,
) -> list:
    DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")

    if not DEVELOPER_TOKEN or not access_token:
        raise HTTPException(
            status_code=401, detail="Missing Google Ads credentials or tokens"
        )

    url = f"https://googleads.googleapis.com/v21/customers/{customer_id}/googleAds:searchStream"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": DEVELOPER_TOKEN,
        "login-customer-id": login_customer_id,
        "Content-Type": "application/json",
    }

    duration_clause = format_duration_clause(duration)

    query = f"""
    SELECT campaign.id,
           campaign.name,
           ad_group.id,
           ad_group.name,
           age_range_view.resource_name,
           ad_group_criterion.age_range.type,
           metrics.impressions,
           metrics.clicks,
           metrics.conversions,
           metrics.cost_micros
    FROM age_range_view
    WHERE segments.date {duration_clause}
      AND campaign.id = {campaign_id}
      AND ad_group.status = 'ENABLED'
    """

    payload = {"query": query}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=headers, json=payload)

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Age Metrics fetch failed: {response.text}",
            )

        metrics_data = []
        try:
            for chunk in response.json():
                metrics_data.extend(chunk.get("results", []))
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to parse metrics response: {str(e)}"
            )

        return metrics_data
