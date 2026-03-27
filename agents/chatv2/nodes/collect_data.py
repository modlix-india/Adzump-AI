"""Data Collection Node - Collects campaign business information via AI conversation."""

import json
import re
from datetime import datetime
from typing import Any, Callable, Optional

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.config import get_config, get_stream_writer
from structlog import get_logger

from agents.chatv2.dependencies import get_llm_adapter
from core.chatv2.fields import REQUIRED_FIELDS
from core.chatv2.models import ChatStatus
from agents.chatv2.state import ChatState
from agents.chatv2.tools import UPDATE_AD_PLAN_TOOL_NAME, get_collection_tools
from core.chatv2.validator import validate_fields
from utils.prompt_loader import load_prompt

logger = get_logger(__name__)


def _get_system_prompt() -> str:
    template = load_prompt("chatv2/collect_data.txt")
    return template.format(TODAY=datetime.now().strftime("%Y-%m-%d"))


async def collect_data_node(state: ChatState) -> dict[str, Any]:
    """Collect campaign business data through AI-powered conversation."""
    logger.info("Entering collect_data_node")
    writer = get_stream_writer()

    ad_plan = dict(state.get("ad_plan") or {})
    session_id = get_config()["configurable"]["thread_id"]

    messages = [
        SystemMessage(content=_get_system_prompt()),
        *state["messages"],
        SystemMessage(content=_build_context(ad_plan, session_id)),
    ]

    reply_text, tool_calls, response = await get_llm_adapter().chat_with_tools(
        messages=messages,
        tools=get_collection_tools(),
        tool_choice="auto",
    )

    _emit_reasoning(writer, tool_calls)
    ad_plan, tool_result = await _process_tool_call(
        tool_calls, ad_plan, writer, session_id
    )

    # Fallback: LLM sometimes re-extracts old fields and misses the URL.
    # Detect URL in latest message programmatically when LLM fails to.
    if "websiteURL" not in ad_plan:
        ad_plan = await _fallback_url_extract(state, ad_plan, writer, session_id)

    if _has_all_fields(ad_plan):
        ad_plan = _predict_budget_if_needed(ad_plan, writer)
        new_status = ChatStatus.SELECTING_PARENT_ACCOUNT
        platform = ad_plan.get("platform", "google")
        label = "Meta" if platform == "meta" else "Google"
        writer(
            {
                "type": "progress",
                "node": "collect_data",
                "phase": "update",
                "content": f"All details collected! Moving to {label} account selection...",
            }
        )
        # Use LLM's reply if it produced one, otherwise brief acknowledgment
        if reply_text.strip():
            response_message = reply_text.strip()
        elif tool_calls:
            response_message = f"Got it! Setting up your {label} campaign..."
        else:
            response_message = ""
    else:
        if tool_result:
            reply_text = await _get_followup_response(
                state, tool_calls, response, tool_result
            )
        elif not reply_text.strip() and tool_calls:
            reply_text = await _get_continuation_response(state, ad_plan)
        response_message = reply_text.strip()
        new_status = state["status"]

    return {
        "ad_plan": ad_plan,
        "messages": [AIMessage(content=response_message)] if response_message else [],
        "response_message": response_message,
        "status": new_status,
    }


async def _process_tool_call(
    tool_calls: list, ad_plan: dict, writer: Callable, session_id: str
) -> tuple[dict, Optional[dict]]:
    """Process update_ad_plan tool call. Returns (ad_plan, tool_result_if_failed)."""
    tool_call = next(
        (tc for tc in tool_calls if tc.get("name") == UPDATE_AD_PLAN_TOOL_NAME),
        None,
    )
    if not tool_call:
        return ad_plan, None

    args = {k: v for k, v in tool_call.get("args", {}).items() if k != "reasoning"}
    valid, errors = await validate_fields(args)

    if valid:
        ad_plan = {**ad_plan, **valid}
        for field, value in valid.items():
            writer(
                {
                    "type": "field_update",
                    "field": field,
                    "value": str(value),
                    "status": "valid",
                }
            )
        logger.info("Extracted campaign data", data=valid)

        if "websiteURL" in valid:
            _start_background_scrape(session_id, valid["websiteURL"])
            writer(
                {
                    "type": "field_update",
                    "field": "websiteSummary",
                    "value": "Analyzing website...",
                    "status": "pending",
                }
            )

    if errors:
        for field, error_msg in errors.items():
            writer(
                {
                    "type": "field_update",
                    "field": field,
                    "value": str(args.get(field, "")),
                    "status": "invalid",
                    "error": error_msg,
                }
            )

    if not errors:
        return ad_plan, None

    return ad_plan, {"saved": valid, "errors": errors}


async def _get_followup_response(
    state: ChatState, tool_calls: list, first_response: AIMessage, tool_result: dict
) -> str:
    """Get AI response after tool validation failed."""
    tool_call = next(
        tc for tc in tool_calls if tc.get("name") == UPDATE_AD_PLAN_TOOL_NAME
    )

    messages = [
        SystemMessage(content=_get_system_prompt()),
        *state["messages"],
        AIMessage(content="", tool_calls=first_response.tool_calls),
        ToolMessage(content=json.dumps(tool_result), tool_call_id=tool_call["id"]),
    ]

    content, _ = await get_llm_adapter().chat(messages)
    return content


async def _get_continuation_response(state: ChatState, ad_plan: dict) -> str:
    """Get AI response when tool succeeded but LLM didn't provide conversational reply."""
    required = _get_dynamic_required(ad_plan)
    missing = [f for f in required if f not in ad_plan]
    messages = [
        SystemMessage(content=_get_system_prompt()),
        *state["messages"],
        SystemMessage(
            content=f"[SYSTEM] Tool call succeeded. Acknowledge what was saved and continue. Still need: {missing if missing else 'nothing — all fields collected'}."
        ),
    ]

    content, _ = await get_llm_adapter().chat(messages)
    return content


def _has_all_fields(ad_plan: dict) -> bool:
    if not all(f in ad_plan for f in REQUIRED_FIELDS):
        return False
    platform = ad_plan.get("platform")
    if platform == "google":
        return "budget" in ad_plan or "targetLeads" in ad_plan
    return "budget" in ad_plan


def _emit_reasoning(writer: Callable, tool_calls: list) -> None:
    """Emit LLM reasoning from tool call args as progress events."""
    for tc in tool_calls:
        reasoning = tc.get("args", {}).get("reasoning")
        if reasoning:
            writer(
                {
                    "type": "progress",
                    "node": "collect_data",
                    "phase": "update",
                    "content": str(reasoning),
                }
            )


def _get_dynamic_required(ad_plan: dict) -> list[str]:
    """Required fields based on current platform context."""
    base = list(REQUIRED_FIELDS)
    platform = ad_plan.get("platform")
    if not platform:
        return base
    if platform == "google":
        if "budget" not in ad_plan:
            base.append("targetLeads")
    else:
        base.append("budget")
    return base


def _start_background_scrape(session_id: str, url: str) -> None:
    """Fire-and-forget background website scrape via ScrapeAgent."""
    from core.infrastructure.context import get_auth_context
    from agents.chatv2.scrape_manager import AuthParams, get_scrape_task_manager

    auth = get_auth_context()
    get_scrape_task_manager().start_scrape(
        session_id=session_id,
        url=url,
        auth=AuthParams(
            access_token=auth.access_token,
            client_code=auth.client_code,
            x_forwarded_host=auth.x_forwarded_host,
            x_forwarded_port=auth.x_forwarded_port,
        ),
    )


def _build_context(ad_plan: dict, session_id: str) -> str:
    """Build context with collected fields + scrape intelligence for LLM."""
    required = _get_dynamic_required(ad_plan)
    collected = {f: ad_plan[f] for f in required if f in ad_plan}
    missing = [f for f in required if f not in ad_plan]
    total = len(required)
    n = len(collected)

    parts = []
    if not collected:
        parts.append("[CONTEXT] No fields collected yet.")
    else:
        parts.append(
            f"[CONTEXT] Collected ({n}/{total}): {json.dumps(collected)}. "
            f"Still need: {missing}."
        )

    scrape = _get_scrape_context(ad_plan, session_id)
    if scrape:
        parts.append(scrape)

    return "\n\n".join(parts)


def _get_scrape_context(ad_plan: dict, session_id: str) -> str | None:
    """Extract business intelligence from scrape for LLM context."""
    from agents.chatv2.scrape_manager import get_scrape_task_manager

    ws = ad_plan.get("websiteSummary")
    if isinstance(ws, dict) and "error" not in ws:
        return _format_scrape_for_llm(ws)

    mgr = get_scrape_task_manager()
    partial = mgr.get_partial_summary(session_id)
    if partial:
        return (
            "[SCRAPE_DATA] (partial — analysis ongoing)\n"
            f"Summary: {partial.get('summary', '')}"
        )

    if mgr.has_active_scrape(session_id):
        return "[SCRAPE_DATA] Website analysis in progress. Infer what you can from the user's message."

    return None


def _format_scrape_for_llm(summary: dict) -> str:
    """Format full scrape result as LLM context."""
    parts = ["[SCRAPE_DATA]"]
    if summary.get("business_type"):
        parts.append(f"Business type: {summary['business_type']}")
    if summary.get("summary"):
        parts.append(f"About: {summary['summary'][:500]}")

    loc = summary.get("location")
    if isinstance(loc, dict):
        loc_parts = [v for k, v in loc.items() if v and isinstance(v, str)]
        if loc_parts:
            parts.append(f"Location: {', '.join(loc_parts[:3])}")

    geo = summary.get("suggested_geo_targets")
    if geo:
        names = [g.get("name", "") for g in geo[:5] if g.get("name")]
        if names:
            parts.append(f"Geo targets: {', '.join(names)}")

    return "\n".join(parts)


def _predict_budget_if_needed(ad_plan: dict, writer: Callable) -> dict:
    """Predict budget from targetLeads when Google + no budget. Returns updated ad_plan."""
    if ad_plan.get("platform") != "google":
        return ad_plan
    if "budget" in ad_plan or "targetLeads" not in ad_plan:
        return ad_plan

    import math
    from mlops.google_search.budget_prediction.api import get_initialized_predictor

    predictor = get_initialized_predictor()
    if not predictor.is_ready():
        logger.warning("budget_predictor_not_ready")
        return ad_plan

    target_leads = ad_plan["targetLeads"]
    duration_days = ad_plan["durationDays"]
    result = predictor.predict(conversions=target_leads, duration_days=duration_days)

    raw = result.suggested_budget / duration_days
    daily_budget = int(math.ceil(raw / 1000) * 1000) if raw > 1000 else int(math.ceil(raw / 100) * 100)
    ad_plan = {**ad_plan, "budget": str(daily_budget)}

    writer({"type": "field_update", "field": "budget", "value": str(daily_budget), "status": "valid"})
    logger.info("budget_predicted", target_leads=target_leads, daily_budget=daily_budget)
    return ad_plan


_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?[a-zA-Z0-9][-a-zA-Z0-9]*(?:\.[a-zA-Z0-9][-a-zA-Z0-9]*)*\.[a-zA-Z]{2,}(?:/\S*)?"
)


async def _fallback_url_extract(
    state: ChatState, ad_plan: dict, writer: Callable, session_id: str
) -> dict:
    """Detect URL in latest user message when LLM fails to extract it."""
    messages = state.get("messages", [])
    if not messages:
        return ad_plan

    content = messages[-1].content if hasattr(messages[-1], "content") else ""
    latest = content if isinstance(content, str) else ""
    match = _URL_RE.search(latest)
    if not match:
        return ad_plan

    valid, _ = await validate_fields({"websiteURL": match.group(0)})
    if "websiteURL" not in valid:
        return ad_plan

    ad_plan = {**ad_plan, "websiteURL": valid["websiteURL"]}
    writer({"type": "field_update", "field": "websiteURL", "value": valid["websiteURL"], "status": "valid"})
    logger.info("URL fallback extraction", url=valid["websiteURL"])
    _start_background_scrape(session_id, valid["websiteURL"])
    writer({"type": "field_update", "field": "websiteSummary", "value": "Analyzing website...", "status": "pending"})
    return ad_plan
