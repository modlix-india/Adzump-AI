from fastapi import HTTPException
from typing import Dict, Any, List
from structlog import get_logger
import json

from models.age_model import AgeOptimizationResponse
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from oserver.services.connection import fetch_google_api_token_simple
from third_party.google.services.age_service import fetch_age_metrics

logger = get_logger(__name__)


# ---------------------- Calculate Performance Metrics ----------------------
def calculate_performance_metrics(metrics_data: List[dict]) -> List[dict]:
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
            "CPC": round(cpc, 2),
        }

        calculated.append(entry)

    return calculated


# ---------------------- Generate Age Optimization ----------------------
async def generate_age_optimizations(
    customer_id: str,
    login_customer_id: str,
    campaign_id: str,
    client_code: str,
    duration: str,
) -> Dict[str, Any]:
    try:
        access_token = fetch_google_api_token_simple(client_code=client_code)

        metrics = await fetch_age_metrics(
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            access_token=access_token,
            campaign_id=campaign_id,
            duration=duration,
        )
        logger.debug("Fetched raw age metrics", sample=metrics[:2])
        calculated_metrics = calculate_performance_metrics(metrics)
        logger.debug("Calculated age metrics", sample=calculated_metrics[:2])

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
                                "optimized_age_groups": [],
                                "rationale_summary": "No metrics data found for this campaign.",
                            }
                        ],
                    }
                ]
            }

        prompt_template = load_prompt("age_optimization_prompt.txt")
        formatted_prompt = prompt_template.format(
            metrics=json.dumps(calculated_metrics, indent=2),
        )

        response = await chat_completion(
            messages=[
                {"role": "system", "content": "You are an expert Google Ads analyst."},
                {"role": "user", "content": formatted_prompt},
            ],
            model="gpt-4o-mini",
        )

        # Parse LLM response
        try:
            if isinstance(response, dict):
                parsed_response = AgeOptimizationResponse(**response)
            else:
                content = response.choices[0].message.content.strip()
                if content.startswith("```"):
                    content = "\n".join(content.splitlines()[1:-1]).strip()
                parsed_response = AgeOptimizationResponse.model_validate_json(content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM parsing failed: {str(e)}")

        return parsed_response.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Age optimization failed: {str(e)}"
        )
