from fastapi import HTTPException
from typing import Dict, Any
import json
import httpx
import re
import os
from dotenv import load_dotenv

from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from oserver.connection import fetch_google_api_token_simple

load_dotenv()

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
        # 1️⃣ Fetch access token
        access_token = fetch_google_api_token_simple(client_code=client_code)

        # 2️⃣ Fetch data
        audit_logs = await fetch_audit_logs(customer_id, login_customer_id, access_token, campaign_id, start_date, end_date)
        metrics = await fetch_campaign_metrics(customer_id, login_customer_id, access_token, campaign_id, start_date, end_date)

        print("\n========= AUDIT LOGS =========")
        print(json.dumps(audit_logs, indent=2))
        print("\n========= METRICS DATA =========")
        print(json.dumps(metrics, indent=2))

        # 3️⃣ Handle Case 3: No audit logs & all-zero metrics
        if (not audit_logs or len(audit_logs) == 0) and _metrics_all_zero(metrics):
            print("⚠️ No audit logs or all-zero metrics → returning 'No budget suggestions'")
            return {
                "campaign_id": campaign_id,
                "recommended_budget": {
                    "suggested_amount": "No budget suggestions",
                    "rationale": "No audit logs or campaign performance metrics available to generate recommendation."
                }
            }

        # 4️⃣ Case 1 or 2: Data present → Send to LLM for recommendation
        prompt_template = load_prompt("budget_recommendation_prompt.txt")
        formatted_prompt = prompt_template.format(
            audit_logs=json.dumps(audit_logs, indent=2),
            metrics=json.dumps(metrics, indent=2),
            campaign_id=campaign_id
        )

        response = await chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert Google Ads budget analyst. "
                        "Analyze the provided audit logs and campaign metrics. "
                        "Recommend a new daily budget that can increase, decrease, or maintain, "
                        "based purely on performance insights and budget history."
                    )
                },
                {"role": "user", "content": formatted_prompt}
            ],
            model="gpt-4o-mini"
        )

        # 5️⃣ Parse LLM response safely
        parsed = {}
        if isinstance(response, dict):
            parsed = response
        else:
            content_clean = response.strip().replace('\\"', '"')
            try:
                parsed = json.loads(content_clean)
            except json.JSONDecodeError:
                campaign_id_match = re.search(r'"campaign_id"\s*:\s*"([^"]*)"', content_clean)
                suggested_amount_match = re.search(r'"suggested_amount"\s*:\s*("[^"]*"|\d+)', content_clean)
                rationale_match = re.search(r'"rationale"\s*:\s*"([^"]*)"', content_clean)
                parsed = {
                    "campaign_id": campaign_id_match.group(1) if campaign_id_match else campaign_id,
                    "recommended_budget": {
                        "suggested_amount": suggested_amount_match.group(1) if suggested_amount_match else "",
                        "rationale": rationale_match.group(1) if rationale_match else "No rationale provided."
                    }
                }

        # 6️⃣ Validate and finalize amounts
        suggested_amount = parsed["recommended_budget"].get("suggested_amount", "")
        try:
            if isinstance(suggested_amount, str):
                suggested_amount = suggested_amount.replace('"', '').strip()
            suggested_amount_value = float(suggested_amount)
        except (ValueError, TypeError):
            raise HTTPException(status_code=500, detail=f"Invalid suggested_amount value: {suggested_amount}")

        # Convert to micros
        suggested_amount_micros = int(suggested_amount_value)

        return {
            "campaign_id": parsed.get("campaign_id", campaign_id),
            "recommended_budget": {
                "suggested_amount_micros": suggested_amount_micros,
                "rationale": parsed["recommended_budget"].get("rationale", "No rationale provided.")
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Budget recommendation failed: {str(e)}")
