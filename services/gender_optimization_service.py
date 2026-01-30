from fastapi import HTTPException
from structlog import get_logger
from typing import Dict, Any
import json

from models.gender_model import GenderOptimizationResponse
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from utils.metrics_utils import calculate_performance_metrics
from oserver.services.connection import fetch_google_api_token_simple
from third_party.google.services.gender_service import fetch_gender_metrics

logger = get_logger(__name__)


# ---------------------- Generate Gender Optimization ----------------------
async def generate_gender_optimizations(
    customer_id: str,
    login_customer_id: str,
    campaign_id: str,
    client_code: str,
    duration: str,
) -> Dict[str, Any]:
    try:
        access_token = fetch_google_api_token_simple(client_code=client_code)

        metrics = await fetch_gender_metrics(
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            access_token=access_token,
            campaign_id=campaign_id,
            duration=duration,
        )

        logger.debug(
            "Fetched raw gender metrics",
            sample=metrics[:2] if metrics else [],
            campaign_id=campaign_id,
        )

        calculated_metrics = calculate_performance_metrics(metrics)
        logger.debug(
            "Calculated gender metrics",
            sample=calculated_metrics[:2] if calculated_metrics else [],
        )

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
                                "rationale_summary": "No gender-based metrics data found.",
                            }
                        ],
                    }
                ]
            }

        prompt_template = load_prompt("gender_optimization_prompt.txt")
        formatted_prompt = prompt_template.format(
            metrics=json.dumps(calculated_metrics, indent=2)
        )

        response = await chat_completion(
            messages=[
                {"role": "system", "content": "You are an expert Google Ads analyst."},
                {"role": "user", "content": formatted_prompt},
            ],
            model="gpt-4o-mini",
        )
        logger.info("After chat_completion", response=response)

        # Parse LLM response
        try:
            if isinstance(response, dict):
                parsed_response = GenderOptimizationResponse(**response)
            else:
                content = response.choices[0].message.content.strip()
                if content.startswith("```"):
                    content = "\n".join(content.splitlines()[1:-1]).strip()
                parsed_response = GenderOptimizationResponse.model_validate_json(
                    content
                )
        except Exception as e:
            logger.error("LLM parsing failed", error=str(e))
            raise HTTPException(status_code=500, detail=f"LLM parsing failed: {str(e)}")

        return parsed_response.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Gender optimization failed", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Gender optimization failed: {str(e)}"
        )
