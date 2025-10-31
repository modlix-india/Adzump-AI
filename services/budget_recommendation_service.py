from fastapi import HTTPException
from typing import Dict, Any
import json
import httpx
import os

from models.budget_model import BudgetRecommendationResponse
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from oserver.services.connection import fetch_google_api_token_simple


DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")

# ---------------------- Fetch Audit Logs ----------------------
async def fetch_audit_logs(customer_id: str, login_customer_id: str, access_token: str,
                           campaign_id: str, start_date: str, end_date: str) -> list:
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
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Audit log fetch failed: {response.text}"
            )

        audit_events = []
        for chunk in response.json():
            audit_events.extend(chunk.get("results", []))
        return audit_events


# ---------------------- Fetch Campaign Metrics ----------------------
async def fetch_campaign_metrics(customer_id: str, login_customer_id: str, access_token: str,
                                 campaign_id: str, start_date: str, end_date: str) -> list:
    url = f"https://googleads.googleapis.com/v21/customers/{customer_id}/googleAds:searchStream"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": DEVELOPER_TOKEN,
        "login-customer-id": login_customer_id,
        "Content-Type": "application/json"
    }

    query = f"""
    SELECT
      campaign.id,
      campaign.name,
      metrics.clicks,
      metrics.impressions,
      metrics.conversions,
      metrics.cost_micros
    FROM campaign
    WHERE campaign.id = {campaign_id}
      AND segments.date BETWEEN '{start_date}' AND '{end_date}'
    """
    payload = {"query": query}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Metrics fetch failed: {response.text}"
            )

        metrics = []
        for chunk in response.json():
            metrics.extend(chunk.get("results", []))
        return metrics


# ---------------------- Utility: Metrics Check ----------------------
def _metrics_all_zero(metrics_data: list) -> bool:
    """Return True if metrics are empty or all key metrics are zero."""
    if not metrics_data:
        return True

    metrics = metrics_data[0].get("metrics", {})
    keys = ["clicks", "impressions", "conversions", "costMicros"]

    return all(float(metrics.get(k, 0)) == 0 for k in keys)


# ---------------------- Generate Budget Recommendation ----------------------
async def generate_budget_recommendation_service(customer_id: str, login_customer_id: str,
                                                 campaign_id: str, start_date: str, end_date: str,
                                                 client_code: str) -> Dict[str, Any]:
    try:
        # Fetch access token
        access_token = fetch_google_api_token_simple(client_code=client_code)
        
        audit_logs = await fetch_audit_logs(customer_id, login_customer_id, access_token, campaign_id, start_date, end_date)
        metrics = await fetch_campaign_metrics(customer_id, login_customer_id, access_token, campaign_id, start_date, end_date)

        # Handle No audit logs & all-zero metrics
        if (not audit_logs or len(audit_logs) == 0) and _metrics_all_zero(metrics):
            return {
                "campaign_id": campaign_id,
                "recommended_budget": {
                    "suggested_amount": "No budget suggestions",
                    "rationale": "No audit logs or campaign performance metrics available to generate recommendation."
                }
            }

        # Data present → Send to LLM for recommendation
        prompt_template = load_prompt("budget_recommendation_prompt.txt")
        formatted_prompt = prompt_template.format(
            audit_logs=json.dumps(audit_logs, indent=2),
            metrics=json.dumps(metrics, indent=2),
            campaign_id=campaign_id
        )

        response = await chat_completion(
            messages=[
                {"role": "system", "content": "You are an expert Google Ads budget analyst."},
                {"role": "user", "content": formatted_prompt}
            ],
            model="gpt-4o-mini"
        )
        
        # Parse response using Pydantic schema
        try:
            if isinstance(response, dict):
                parsed_response = BudgetRecommendationResponse(**response)
            else:
                content = response.choices[0].message.content.strip()
                # Strip markdown code block if present
                if content.startswith("```"):
                    content = "\n".join(content.splitlines()[1:-1]).strip()
                    
                parsed_response = BudgetRecommendationResponse.model_validate_json(content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM response parsing failed: {str(e)}")

        suggested_amount_micros = int(parsed_response.recommended_budget.suggested_amount)

        return {
            "campaign_id": parsed_response.campaign_id,
            "recommended_budget": {
                "suggested_amount_micros": suggested_amount_micros,
                "rationale": parsed_response.recommended_budget.rationale
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Budget recommendation failed: {str(e)}")
