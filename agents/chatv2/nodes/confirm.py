"""Confirmation Node - Handles campaign confirmation flow."""

from typing import Any, Callable, Optional

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.config import get_config, get_stream_writer
from structlog import get_logger

from agents.chatv2.platform_config import PLATFORM_CONFIG
from agents.chatv2.state import ChatState
from core.chatv2.models import AccountSelection, ChatStatus
from core.chatv2.validator import validate_fields
from agents.chatv2.dependencies import get_llm_adapter
from agents.chatv2.tools import (
    CONFIRM_CAMPAIGN_TOOL_NAME,
    HANDLE_ACCOUNT_SELECTION_TOOL_NAME,
    UPDATE_AD_PLAN_TOOL_NAME,
    get_confirmation_tools,
)
from utils.helpers import get_today_end_date_with_duration
from utils.prompt_loader import load_prompt

logger = get_logger(__name__)


async def show_summary_node(state: ChatState) -> dict[str, Any]:
    """Build and display campaign summary. Runs once when entering confirmation."""
    writer = get_stream_writer()
    ad_plan = dict(state["ad_plan"])
    summary = build_summary(ad_plan, state)
    writer(
        {
            "type": "progress",
            "node": "show_summary",
            "phase": "end",
            "label": "Awaiting confirmation",
        }
    )
    return {
        "response_message": summary,
        "messages": [AIMessage(content=summary)],
    }


async def confirm_node(state: ChatState) -> dict[str, Any]:
    """Handle user response to campaign summary — confirm, modify, or change account."""
    logger.info("Entering confirm_node")
    writer = get_stream_writer()

    ad_plan = dict(state["ad_plan"])

    messages = [
        SystemMessage(content=_get_system_prompt()),
        *state["messages"],
    ]

    ai_content, tool_calls, _ = await get_llm_adapter().chat_with_tools(
        messages=messages,
        tools=get_confirmation_tools(),
    )

    if tool_calls:
        for tool_call in tool_calls:
            fname = tool_call.get("name", "")
            reasoning = tool_call.get("args", {}).get("reasoning", "")
            if reasoning:
                writer(
                    {
                        "type": "progress",
                        "node": "confirm",
                        "phase": "update",
                        "content": reasoning,
                    }
                )

            if fname == CONFIRM_CAMPAIGN_TOOL_NAME:
                writer(
                    {
                        "type": "progress",
                        "node": "confirm",
                        "phase": "update",
                        "content": "Campaign confirmed! Finalizing details...",
                    }
                )
                return await _handle_confirmation(state, ad_plan)
            elif fname == UPDATE_AD_PLAN_TOOL_NAME:
                return await _handle_field_modification(
                    state, tool_call, ad_plan, writer
                )
            elif fname == HANDLE_ACCOUNT_SELECTION_TOOL_NAME:
                writer(
                    {
                        "type": "progress",
                        "node": "confirm",
                        "phase": "update",
                        "content": "Switching account selection...",
                    }
                )
                return await _handle_account_change(state, tool_call, ad_plan)

    final_message = ai_content or "What would you like to change?"

    return {
        "response_message": final_message,
        "messages": [AIMessage(content=final_message)],
    }


def build_summary(ad_plan: dict, state: ChatState) -> str:
    """Build confirmation summary."""
    config = _get_config(ad_plan)
    lines = ["I have the following details for your campaign:"]

    field_labels = {
        "platform": "Platform",
        "productName": "Product Name",
        "websiteURL": "Website",
        "budget": "Budget",
        "durationDays": "Duration",
        config["parent_id_field"]: config["parent_label"].capitalize(),
        config["account_id_field"]: config["account_label"].capitalize(),
    }

    for field, label in field_labels.items():
        if field not in ad_plan:
            continue
        value = ad_plan[field]

        if field == "platform":
            value = "Google Ads" if value == "google" else "Meta Ads"
        elif field == "budget":
            value = f"\u20b9{int(float(value)):,}"
        elif field == "durationDays":
            value = f"{value} days"
        elif field == config["parent_id_field"]:
            name = _find_account_name(state.get("parent_account_options", []), value)
            if name:
                value = f"{name} ({value})"
        elif field == config["account_id_field"]:
            name = _find_account_name(state.get("account_options", []), value)
            if name:
                value = f"{name} ({value})"

        lines.append(f"- {label}: {value}")

    location = ad_plan.get("location")
    if isinstance(location, dict):
        loc_name = location.get("product_location") or location.get("area_location")
        if loc_name:
            lines.append(f"- Location: {loc_name}")

    competitors = ad_plan.get("competitors")
    if isinstance(competitors, list) and competitors:
        lines.append(f"- Competitors: {', '.join(competitors)}")

    lines.append("\nPlease confirm if everything is correct.")
    return "\n".join(lines)


async def _handle_confirmation(state: ChatState, ad_plan: dict) -> dict[str, Any]:
    config = _get_config(ad_plan)
    duration_days = int(ad_plan.get("durationDays", 7))
    dates = get_today_end_date_with_duration(duration_days)
    ad_plan.update(dates)

    ad_plan["budget"] = int(float(ad_plan.get("budget", 0)))
    duration = int(ad_plan.get("durationDays", 7))
    ad_plan["durationDays"] = "1 Day" if duration == 1 else f"{duration} Days"

    parent_name = _find_account_name(
        state.get("parent_account_options", []),
        ad_plan.get(config["parent_id_field"], ""),
    )
    if parent_name:
        ad_plan[config["parent_id_field"] + "Name"] = parent_name

    account_name = _find_account_name(
        state.get("account_options", []),
        ad_plan.get(config["account_id_field"], ""),
    )
    if account_name:
        ad_plan[config["account_id_field"] + "Name"] = account_name

    return {
        "ad_plan": ad_plan,
        "status": ChatStatus.COMPLETED,
        "response_message": "",
    }


async def _handle_field_modification(
    state: ChatState, tool_call: dict, ad_plan: dict, writer: Callable
) -> dict[str, Any]:
    args = {k: v for k, v in tool_call.get("args", {}).items() if k != "reasoning"}
    valid, errors = await validate_fields(args)

    ai_message = ""
    if valid:
        ad_plan.update(valid)
        for field, value in valid.items():
            writer(
                {
                    "type": "field_update",
                    "field": field,
                    "value": str(value),
                    "status": "valid",
                }
            )
    if errors:
        ai_message = " ".join(errors.values())
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

    if "websiteURL" in valid:
        _start_background_scrape(
            get_config()["configurable"]["thread_id"], valid["websiteURL"]
        )
        writer(
            {
                "type": "field_update",
                "field": "websiteSummary",
                "value": "Analyzing website...",
                "status": "pending",
            }
        )

    if "platform" in valid:
        return _handle_platform_change(ad_plan, state, ai_message)

    summary = build_summary(ad_plan, state)
    full_message = f"{ai_message}\n\n{summary}" if ai_message else summary

    return {
        "ad_plan": ad_plan,
        "response_message": full_message,
        "messages": [AIMessage(content=full_message)],
    }


async def _handle_account_change(
    state: ChatState, tool_call: dict, ad_plan: dict
) -> dict[str, Any]:
    config = _get_config(ad_plan)
    args = tool_call.get("args", {})
    action = (args.get("action") or "").lower()

    if action in ("parent_account", "both"):
        ad_plan.pop(config["parent_id_field"], None)
        ad_plan.pop(config["account_id_field"], None)
        return {
            "ad_plan": ad_plan,
            "account_options": [],
            "status": ChatStatus.SELECTING_PARENT_ACCOUNT,
            "response_message": f"Here are your {config['parent_label']}s:",
            "account_selection": AccountSelection.parent_account_selection(
                state.get("parent_account_options", [])
            ).model_dump(),
        }
    elif action == "account":
        ad_plan.pop(config["account_id_field"], None)
        return {
            "ad_plan": ad_plan,
            "status": ChatStatus.SELECTING_ACCOUNT,
            "response_message": f"Here are the {config['account_label']}s:",
            "account_selection": AccountSelection.account_selection(
                state.get("account_options", [])
            ).model_dump(),
        }

    return {
        "response_message": "I didn't understand which account to change.",
    }


def _handle_platform_change(
    ad_plan: dict, state: ChatState, ai_message: str
) -> dict[str, Any]:
    """Clear old platform's account fields and restart account selection.

    TODO: Full platform switch should also re-prompt for any platform-specific
    fields (e.g. Meta may need different targeting info). Currently only clears
    account IDs and restarts account selection flow.
    """
    for platform_key in PLATFORM_CONFIG:
        config = PLATFORM_CONFIG[platform_key]
        if platform_key != ad_plan["platform"]:
            ad_plan.pop(config["parent_id_field"], None)
            ad_plan.pop(config["account_id_field"], None)

    summary = build_summary(ad_plan, state)
    full_message = f"{ai_message}\n\n{summary}" if ai_message else summary

    return {
        "ad_plan": ad_plan,
        "parent_account_options": [],
        "account_options": [],
        "status": ChatStatus.SELECTING_PARENT_ACCOUNT,
        "response_message": full_message,
        "messages": [AIMessage(content=full_message)],
    }


def _find_account_name(accounts: list[dict], account_id: str) -> Optional[str]:
    """Find account name by ID from a list of accounts."""
    for account in accounts:
        if str(account.get("id")) == str(account_id):
            return account.get("name")
    return None


def _get_config(ad_plan: dict) -> dict:
    platform = ad_plan.get("platform", "google")
    return PLATFORM_CONFIG[platform]


def _get_system_prompt() -> str:
    """Load the confirm prompt."""
    return load_prompt("chatv2/confirm.txt")



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
