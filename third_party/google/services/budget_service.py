from fastapi import HTTPException
from datetime import date, timedelta
import httpx
import os
from oserver.connection import fetch_google_api_token_simple

DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")


# ---------------------- Fetch Audit Logs ----------------------
async def fetch_audit_logs(customer_id: str, login_customer_id: str, access_token: str, campaign_id: str) -> list:
    end_date = date.today()
    start_date = end_date - timedelta(days=29)
    
    url = f"https://googleads.googleapis.com/v21/customers/{customer_id}/googleAds:searchStream"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": DEVELOPER_TOKEN,
        "login-customer-id": login_customer_id,
        "Content-Type": "application/json"
    }

    query = f"""
    SELECT
      change_event.change_date_time,
      change_event.old_resource,
      change_event.new_resource
    FROM change_event
    WHERE change_event.change_resource_type IN ('CAMPAIGN_BUDGET')
      AND change_event.change_date_time BETWEEN '{start_date}' AND '{end_date}'
      AND campaign.id = {campaign_id}
    ORDER BY change_event.change_date_time DESC
    LIMIT 1000
    """
    payload = {"query": query}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Audit log fetch failed: {response.text}")

        audit_events = []
        for chunk in response.json():
            audit_events.extend(chunk.get("results", []))
        return audit_events


# ---------------------- Fetch Campaign Metrics ----------------------
async def fetch_campaign_metrics(customer_id: str, login_customer_id: str, access_token: str, campaign_id: str) -> list:
    url = f"https://googleads.googleapis.com/v21/customers/{customer_id}/googleAds:searchStream"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": DEVELOPER_TOKEN,
        "login-customer-id": login_customer_id,
        "Content-Type": "application/json"
    }

    query = f"""
    SELECT
      segments.date,
      campaign.id,
      campaign.name,
      metrics.clicks,
      metrics.impressions,
      metrics.conversions,
      metrics.cost_micros
    FROM campaign
    WHERE campaign.id = {campaign_id}
      AND segments.date DURING LAST_30_DAYS
    ORDER BY segments.date DESC
    """
    
    payload = {"query": query}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Metrics fetch failed: {response.text}")

        metrics = []
        for chunk in response.json():
            metrics.extend(chunk.get("results", []))
        return metrics


# ---------------------- Fetch Old Budget ----------------------
async def fetch_old_budget(customer_id: str, login_customer_id: str, access_token: str, campaign_id: str) -> dict:
    url = f"https://googleads.googleapis.com/v21/customers/{customer_id}/googleAds:search"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": DEVELOPER_TOKEN,
        "login-customer-id": login_customer_id,
        "Content-Type": "application/json"
    }

    query = f"""
    SELECT
      campaign.id,
      campaign_budget.amount_micros,
      campaign_budget.name
    FROM campaign
    WHERE campaign.id = {campaign_id}
    """

    payload = {"query": query}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Old budget fetch failed: {response.text}")

        data = response.json()
        return data.get("results", [{}])[0].get("campaignBudget", {}).get("amountMicros", 0)


def get_access_token(client_code: str):
    return fetch_google_api_token_simple(client_code=client_code)
