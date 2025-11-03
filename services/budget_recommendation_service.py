from fastapi import HTTPException
from typing import Dict, Any
import json

from models.budget_model import BudgetRecommendationResponse
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from oserver.connection import fetch_google_api_token_simple
from third_party.google.services.budget_service import (
    fetch_audit_logs,
    fetch_campaign_metrics,
    fetch_old_budget
)


# ---------------------- Generate Budget Recommendation ----------------------
async def generate_budget_recommendations(customer_id: str, login_customer_id: str,
                                                 campaign_id: str, client_code: str) -> Dict[str, Any]:
    try:
        access_token = fetch_google_api_token_simple(client_code=client_code)
        
        audit_logs = await fetch_audit_logs(customer_id, login_customer_id, access_token, campaign_id)
        metrics = await fetch_campaign_metrics(customer_id, login_customer_id, access_token, campaign_id)
        old_budget = await fetch_old_budget(customer_id, login_customer_id, access_token, campaign_id)


        # CASE 4: Audit Logs empty + Metrics empty array
        if (not audit_logs or len(audit_logs) == 0) and (not metrics or len(metrics) == 0):
            return {
                "campaign_id": campaign_id,
                "recommended_budget": {
                    "suggested_amount": "No budget suggestions",
                    "old_budget": old_budget,
                    "rationale": "No audit logs or campaign metrics found for the last 30 days."
                }
            }
            
        # CASE 3: Audit Logs + Metrics empty array
        if audit_logs and (not metrics or len(metrics) == 0):
            return {
                "campaign_id": campaign_id,
                "recommended_budget": {
                    "suggested_amount": "No budget suggestions",
                    "old_budget": old_budget,
                    "rationale": "Audit logs found, but campaign metrics are missing for the last 30 days."
                }
            }
            
        # CASE 2: Audit Logs empty + Metrics available
        if (not audit_logs or len(audit_logs) == 0) and metrics:
            # Prepare prompt using old budget + metrics
            prompt_template = load_prompt("budget_recommendation_prompt.txt")
            formatted_prompt = prompt_template.format(
                audit_logs=json.dumps([]),
                old_budget=json.dumps(old_budget, indent=2),
                metrics=json.dumps(metrics, indent=2),
                campaign_id=campaign_id
            )

        # CASE 1: Audit Logs and Metrics both available
        else:
            prompt_template = load_prompt("budget_recommendation_prompt.txt")
            formatted_prompt = prompt_template.format(
                audit_logs=json.dumps(audit_logs, indent=2),
                old_budget=json.dumps({}, indent=2),
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
                if content.startswith("```"):
                    content = "\n".join(content.splitlines()[1:-1]).strip()
                    
                parsed_response = BudgetRecommendationResponse.model_validate_json(content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM response parsing failed: {str(e)}")

        suggested_amount_micros = int(parsed_response.suggested_amount)

        return {
            "campaign_id": parsed_response.campaign_id,
            "recommended_budget": {
                "suggested_amount_micros": suggested_amount_micros,
                "old_budget": old_budget,
                "rationale": parsed_response.rationale
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Budget recommendation failed: {str(e)}")
