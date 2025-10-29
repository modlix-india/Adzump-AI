from fastapi import HTTPException
from typing import List, Dict, Any
import json
import httpx
import os

from models.gender_model import GenderOptimizationResponse
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from oserver.connection import fetch_google_api_token_simple

DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")

# ---------------------- Fetch Campaign Metrics ----------------------
async def fetch_gender_metrics(customer_id: str, login_customer_id: str, access_token: str,
                               campaign_id: str, start_date: str, end_date: str) -> List[dict]:
    url = f"https://googleads.googleapis.com/v21/customers/{customer_id}/googleAds:searchStream"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": DEVELOPER_TOKEN,
        "login-customer-id": login_customer_id,
        "Content-Type": "application/json"
    }

    query = f"""
    SELECT campaign.id,
           campaign.name,
           ad_group.id,
           ad_group.name,
           gender_view.resource_name,
           ad_group_criterion.gender.type,
           metrics.impressions,
           metrics.clicks,
           metrics.conversions,
           metrics.cost_micros
    FROM gender_view
    WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
      AND campaign.id = {campaign_id}
    """

    payload = {"query": query}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=headers, json=payload)

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Metrics fetch failed: {response.text}"
            )

        metrics_data = []
        try: 
            for chunk in response.json():
                metrics_data.extend(chunk.get("results", []))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to parse gender metrics: {str(e)}")

        return metrics_data


# ---------------------- Calculate Performance Metrics ----------------------
def calculate_gender_metrics(metrics_data: List[dict]) -> List[dict]:
    calculated = []
    for entry in metrics_data:
        metrics = entry.get("metrics", {})
        cost_micros = float(metrics.get("costMicros", 0))
        clicks = float(metrics.get("clicks", 0))
        impressions = float(metrics.get("impressions", 0))
        conversions = float(metrics.get("conversions", 0))

        cost = cost_micros / 1_000_000

        cpa = cost / conversions if conversions > 0 else 0.0
        ctr = (clicks / impressions * 100) if impressions > 0 else 0.0
        cpc = cost / clicks if clicks > 0 else 0.0

        entry["calculated_metrics"] = {
            "cost": round(cost, 2),
            "CPA": round(cpa, 2),
            "CTR": round(ctr, 2),
            "CPC": round(cpc, 2)
        }

        calculated.append(entry)
    return calculated


# ---------------------- Generate Gender Optimization ----------------------
async def generate_gender_optimization_service(customer_id: str, login_customer_id: str,
                                               campaign_id: str, start_date: str, end_date: str,
                                               client_code: str) -> Dict[str, Any]:
    try:
        # access_token = fetch_google_api_token_simple(client_code=client_code)
        access_token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN")
        metrics = await fetch_gender_metrics(customer_id, login_customer_id, access_token, campaign_id, start_date, end_date)
        calculated_metrics = calculate_gender_metrics(metrics)

        if not calculated_metrics:
            return {
                "campaigns": [
                    {
                        "campaign_id": campaign_id,
                        "campaign_name": "",
                        "ad_groups": [
                            {
                                "ad_group_id": "",
                                "ad_group_name": "",
                                "optimized_genders": [],
                                "rationale_summary": "No gender-based metrics data found."
                            }
                        ]
                    }
                ]
            }

        prompt_template = load_prompt("gender_optimization_prompt.txt")
        formatted_prompt = prompt_template.format(
            metrics=json.dumps(calculated_metrics, indent=2),
        )

        response = await chat_completion(
            messages=[
                {"role": "system", "content": "You are an expert Google Ads audience analyst."},
                {"role": "user", "content": formatted_prompt}
            ],
            model="gpt-4o-mini"
        )

        try:
            if isinstance(response, dict):
                parsed_response = GenderOptimizationResponse(**response)
            else:
                content = response.choices[0].message.content.strip()
                if content.startswith("```"):
                    content = "\n".join(content.splitlines()[1:-1]).strip()
                parsed_response = GenderOptimizationResponse.model_validate_json(content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM parsing failed: {str(e)}")

        return parsed_response.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gender optimization failed: {str(e)}")
