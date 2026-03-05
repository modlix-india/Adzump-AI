"""Budget Prediction Node - Predicts campaign budget from target leads for Google campaigns."""

import math
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.config import get_stream_writer
from structlog import get_logger

from agents.chatv2.state import ChatState
from core.chatv2.models import ChatStatus
from mlops.google_search.budget_prediction.api import get_initialized_predictor

logger = get_logger(__name__)


async def predict_budget_node(state: ChatState) -> dict[str, Any]:
    """Predict budget from targetLeads + durationDays for Google campaigns.

    Passthrough when: not Google, budget already provided, or no targetLeads.
    Fallback: if model not loaded, revert to IN_PROGRESS so user can provide budget.
    On success: set budget and pause at IN_PROGRESS for user confirmation.
    """
    ad_plan = dict(state.get("ad_plan") or {})

    if not _needs_prediction(ad_plan):
        return {}

    writer = get_stream_writer()
    target_leads = ad_plan["targetLeads"]
    duration_days = ad_plan["durationDays"]

    predictor = get_initialized_predictor()
    if not predictor.is_ready():
        logger.warning("budget_predictor_not_ready", target_leads=target_leads)
        message = (
            "I couldn't estimate the budget automatically. "
            "What's your daily advertising budget?"
        )
        return {
            "status": ChatStatus.IN_PROGRESS,
            "response_message": message,
            "messages": [AIMessage(content=message)],
        }

    result = predictor.predict(
        conversions=target_leads, duration_days=duration_days
    )
    daily_budget = _round_budget(result.suggested_budget / duration_days)
    ad_plan["budget"] = str(daily_budget)

    writer(
        {
            "type": "progress",
            "node": "predict_budget",
            "phase": "start",
            "label": "Estimating campaign budget",
        }
    )

    message = (
        f"Based on your target of {target_leads} leads over {duration_days} days, "
        f"we recommend a daily budget of ₹{daily_budget:,}. "
        f"This factors in average cost-per-lead with a buffer for competitive bidding.\n\n"
        f"Would you like to proceed with ₹{daily_budget:,}/day, "
        f"or would you prefer a different daily budget?"
    )

    writer(
        {
            "type": "progress",
            "node": "predict_budget",
            "phase": "update",
            "content": f"Estimated daily budget: ₹{daily_budget:,}",
        }
    )
    writer(
        {
            "type": "field_update",
            "field": "budget",
            "value": str(daily_budget),
            "status": "valid",
        }
    )

    logger.info(
        "budget_predicted",
        target_leads=target_leads,
        duration_days=duration_days,
        daily_budget=daily_budget,
        total_estimate=result.suggested_budget,
        base_prediction=result.base_cost_prediction,
    )

    return {
        "ad_plan": ad_plan,
        "status": ChatStatus.IN_PROGRESS,
        "response_message": message,
        "messages": [AIMessage(content=message)],
    }


def _needs_prediction(ad_plan: dict) -> bool:
    """Check if budget prediction is needed."""
    if ad_plan.get("platform") != "google":
        return False
    if "budget" in ad_plan:
        return False
    if "targetLeads" not in ad_plan:
        return False
    return True


def _round_budget(amount: float) -> int:
    """Round budget to a clean number for readability."""
    if amount <= 1000:
        return int(math.ceil(amount / 100) * 100)
    return int(math.ceil(amount / 1000) * 1000)
