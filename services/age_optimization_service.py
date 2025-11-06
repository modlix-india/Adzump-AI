from fastapi import HTTPException
from typing import Dict, Any
import json

from models.age_model import AgeOptimizationResponse
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from oserver.services.connection import fetch_google_api_token_simple
from third_party.google.services.age_service import fetch_age_metrics


# ---------------------- Generate Age Optimization ----------------------
async def generate_age_optimizations(customer_id: str, login_customer_id: str, campaign_id: str, client_code: str, duration: str) -> Dict[str, Any]:
    try:
        access_token = fetch_google_api_token_simple(client_code=client_code)

        metrics = await fetch_age_metrics(customer_id, login_customer_id, access_token, campaign_id, duration)

        # Handle Empty Metrics
        if not metrics:
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
                                "rationale_summary": "No age-based metrics data found."
                            }
                        ]
                    }
                ]
            }

        prompt_template = load_prompt("age_optimization_prompt.txt")
        formatted_prompt = prompt_template.format(metrics=json.dumps(metrics, indent=2))

        response = await chat_completion(
            messages=[
                {"role": "system", "content": "You are an expert Google Ads audience analyst."},
                {"role": "user", "content": formatted_prompt}
            ],
            model="gpt-4o-mini"
        )

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
        raise HTTPException(status_code=500, detail=f"Age optimization failed: {str(e)}")