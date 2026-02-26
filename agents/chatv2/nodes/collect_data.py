"""Data Collection Node - Collects campaign business information via AI conversation."""

import json
from datetime import datetime
from typing import Any, Callable, Optional

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.config import get_stream_writer
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
    writer(
        {
            "type": "progress",
            "node": "collect_data",
            "phase": "start",
            "label": "Collecting campaign details",
        }
    )

    ad_plan = dict(state.get("ad_plan") or {})
    messages = [
        SystemMessage(content=_get_system_prompt()),
        *state["messages"],
        SystemMessage(content=_build_context(ad_plan)),
    ]

    tool_choice = "required" if ad_plan else "auto"
    reply_text, tool_calls, response = await get_llm_adapter().chat_with_tools(
        messages=messages,
        tools=get_collection_tools(),
        tool_choice=tool_choice,
    )

    _emit_reasoning(writer, tool_calls)
    ad_plan, tool_result = await _process_tool_call(tool_calls, ad_plan, writer)

    if _has_all_fields(ad_plan):
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
        # Skip follow-up LLM call — next node will provide the response
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
    tool_calls: list, ad_plan: dict, writer: Callable
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
    context = _build_context(ad_plan)
    required = _get_dynamic_required(ad_plan)
    missing = [f for f in required if f not in ad_plan]
    messages = [
        SystemMessage(content=_get_system_prompt()),
        *state["messages"],
        SystemMessage(
            content=f"[SYSTEM] Tool call succeeded. {context} Acknowledge what was saved and ask for the next missing field ({missing[0] if missing else 'none'})."
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


def _build_context(ad_plan: dict) -> str:
    """Build context message with collected values and missing fields."""
    required = _get_dynamic_required(ad_plan)
    collected = {f: ad_plan[f] for f in required if f in ad_plan}
    missing = [f for f in required if f not in ad_plan]
    total = len(required)
    n = len(collected)
    if not collected:
        return (
            "[CONTEXT] No fields collected yet. This is the start of the conversation."
        )
    return (
        f"[CONTEXT] Collected ({n}/{total}): {json.dumps(collected)}. "
        f"Still need: {missing}."
    )
