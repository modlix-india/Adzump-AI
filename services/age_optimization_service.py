from fastapi import HTTPException
from typing import List, Dict, Any
import json
import httpx
import os

from models.age_model import AgeOptimizationResponse
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from oserver.connection import fetch_google_api_token_simple

DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")

# ---------------------- Fetch Campaign Metrics ----------------------
async def fetch_campaign_metrics(customer_id: str, login_customer_id: str, access_token: str,
                                 campaign_id: str, start_date: str, end_date: str) -> List[dict]:
    url = f"https://googleads.googleapis.com/v20/customers/{customer_id}/googleAds:searchStream"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": DEVELOPER_TOKEN,
        "login-customer-id": login_customer_id,
        "Content-Type": "application/json"
    }

    query = f"""
    SELECT campaign.id, campaign.name, metrics.clicks, metrics.impressions,
           metrics.conversions, metrics.cost_micros
    FROM campaign
    WHERE campaign.id = {campaign_id}
      AND segments.date BETWEEN '{start_date}' AND '{end_date}'
    """
    payload = {"query": query}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code,
                                detail=f"Metrics fetch failed: {response.text}")

        metrics_data = []
        for chunk in response.json():
            metrics_data.extend(chunk.get("results", []))
        return metrics_data


# ---------------------- Fetch Age Targeting ----------------------
async def fetch_age_criteria(customer_id: str, login_customer_id: str, access_token: str,
                             campaign_id: str) -> List[dict]:
    url = f"https://googleads.googleapis.com/v20/customers/{customer_id}/googleAds:search"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": DEVELOPER_TOKEN,
        "login-customer-id": login_customer_id,
        "Content-Type": "application/json"
    }

    query = f"""
    SELECT ad_group_criterion.criterion_id, ad_group_criterion.type, ad_group_criterion.age_range.type,
           campaign.name, campaign.id
    FROM ad_group_criterion
    WHERE ad_group_criterion.type = 'AGE_RANGE'
      AND campaign.id = {campaign_id}
    """
    payload = {"query": query}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code,
                                detail=f"Age criteria fetch failed: {response.text}")
        return response.json().get("results", [])


# ---------------------- Utility: Check Zero Metrics ----------------------
def _metrics_all_zero(metrics_data: List[dict]) -> bool:
    if not metrics_data:
        return True
    metrics = metrics_data[0].get("metrics", {})
    keys = ["clicks", "impressions", "conversions", "costMicros"]
    return all(float(metrics.get(k, 0)) == 0 for k in keys)


# ---------------------- Generate Age Optimization ----------------------
async def generate_age_optimization_service(customer_id: str, login_customer_id: str,
                                            campaign_id: str, start_date: str, end_date: str,
                                            client_code: str) -> Dict[str, Any]:
    try:
        # Fetch access token
        access_token = fetch_google_api_token_simple(client_code=client_code)

        metrics = await fetch_campaign_metrics(customer_id, login_customer_id, access_token, campaign_id, start_date, end_date)
        age_criteria = await fetch_age_criteria(customer_id, login_customer_id, access_token, campaign_id)

        # ---------------- Handle zero metrics / no age criteria ----------------
        if _metrics_all_zero(metrics):
            reason = "Metrics are all zero"
            if not age_criteria or len(age_criteria) == 0:
                reason += " and no age targeting found"
            return {
                "campaign_id": campaign_id,
                "optimized_age_groups": [{"age_range": "", "reason": reason}],
                "rationale": reason
            }

        # Prepare LLM prompt
        prompt_template = load_prompt("age_optimization_prompt.txt")
        formatted_prompt = prompt_template.format(
            campaign_id=campaign_id,
            age_criteria=json.dumps(age_criteria, indent=2),
            metrics=json.dumps(metrics, indent=2)
        )

        # Call OpenAI
        response = await chat_completion(
            messages=[
                {"role": "system", "content": "You are an expert Google Ads analyst."},
                {"role": "user", "content": formatted_prompt}
            ],
            model="gpt-4o-mini"
        )

        # Parse LLM response
        try:
            # Get content from LLM response
            if isinstance(response, dict):
                parsed_response = AgeOptimizationResponse(**response)
            else:
                content = response.choices[0].message.content.strip()
                if content.startswith("```"):
                    # Remove markdown backticks if present
                    content = "\n".join(content.splitlines()[1:-1]).strip()
                # Use pydantic to parse JSON strictly
                parsed_response = AgeOptimizationResponse.model_validate_json(content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM parsing failed: {str(e)}")

        # Return JSON dict
        return parsed_response.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Age optimization failed: {str(e)}")
