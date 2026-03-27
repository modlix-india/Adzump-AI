"""Parent Account Selection — fetch and select parent (MCC/Meta Business) accounts."""

from typing import Any

from langgraph.config import get_stream_writer
from structlog import get_logger

from agents.chatv2 import dependencies
from agents.chatv2.platform_config import PLATFORM_CONFIG
from agents.chatv2.state import ChatState
from core.chatv2.models import ChatStatus, AccountSelection
from core.chatv2.validator import validate_account_selection
from core.infrastructure.context import auth_context

logger = get_logger(__name__)


async def fetch_parent_account_options(state: ChatState) -> dict[str, Any]:
    """Fetch parent (MCC / Meta Business) account options."""
    config = _get_config(state)
    client_code = auth_context.client_code
    writer = get_stream_writer()
    label = config["parent_label"]
    writer(
        {
            "type": "progress",
            "node": "fetch_parent_account",
            "phase": "start",
            "label": config["progress_find"],
        }
    )

    logger.info("Fetching parent account options", client_code=client_code, label=label)

    try:
        parents = await getattr(dependencies, config["fetch_parents"])(client_code)
    except Exception:
        logger.exception("Error fetching parent accounts")
        writer(
            {
                "type": "progress",
                "node": "fetch_parent_account",
                "phase": "end",
                "label": f"Error fetching {label}s",
            }
        )
        return {
            "status": ChatStatus.IN_PROGRESS,
            "response_message": f"Couldn't fetch {label}s. Please try again.",
            "account_selection": None,
        }

    if not parents:
        writer(
            {
                "type": "progress",
                "node": "fetch_parent_account",
                "phase": "end",
                "label": f"No {label}s found",
            }
        )
        return {
            "parent_account_options": [],
            "status": ChatStatus.IN_PROGRESS,
            "response_message": f"I couldn't find any {label}s. Please check your connection.",
            "account_selection": None,
        }

    if len(parents) == 1:
        parent = parents[0]
        parent_name = parent.get("name", parent.get("id"))
        parent_id = parent.get("id")
        writer(
            {
                "type": "progress",
                "node": "fetch_parent_account",
                "phase": "end",
                "label": f"Auto-selected {label}: {parent_name}",
            }
        )

        new_ad_plan = dict(state["ad_plan"])
        new_ad_plan[config["parent_id_field"]] = parent_id

        account_attachment = {
            "type": "confirmed_account",
            "name": parent_name,
            "id": parent_id,
            "account_type": "parent",
        }
        reply = f"Found 1 {label} — auto-selected {parent_name}"
        return {
            "ad_plan": new_ad_plan,
            "parent_account_options": parents,
            "status": ChatStatus.SELECTING_ACCOUNT,
            "response_message": reply,
            "intermediate_messages": [{"reply": reply, "attachments": [account_attachment]}],
        }

    writer(
        {
            "type": "progress",
            "node": "fetch_parent_account",
            "phase": "end",
            "label": f"Found {len(parents)} {label}s",
        }
    )
    return {
        "parent_account_options": parents,
        "status": ChatStatus.SELECTING_PARENT_ACCOUNT,
        "response_message": f"Here are your available {label}s:",
        "account_selection": AccountSelection.parent_account_selection(
            parents
        ).model_dump(),
    }


async def select_parent_account_node(state: ChatState) -> dict[str, Any]:
    """Handle parent account selection from user input."""
    writer = get_stream_writer()
    config = _get_config(state)
    writer(
        {
            "type": "progress",
            "node": "select_parent_account",
            "phase": "start",
            "label": config["progress_select_parent"],
        }
    )
    messages = state.get("messages", [])
    parent_options = state.get("parent_account_options", [])

    if not messages:
        writer(
            {
                "type": "progress",
                "node": "select_parent_account",
                "phase": "end",
                "label": f"Waiting for {config['parent_label']} selection",
            }
        )
        return {
            "response_message": f"Please select a {config['parent_label']} from the list.",
            "account_selection": AccountSelection.parent_account_selection(
                parent_options
            ).model_dump(),
        }

    last_message = messages[-1]
    content = (
        last_message.content if hasattr(last_message, "content") else str(last_message)
    )
    selected_id = content.strip() if isinstance(content, str) else str(content)

    if not validate_account_selection(selected_id, parent_options):
        writer(
            {
                "type": "progress",
                "node": "select_parent_account",
                "phase": "end",
                "label": "Invalid selection",
            }
        )
        return {
            "response_message": "Invalid selection. Please choose from the list.",
            "account_selection": AccountSelection.parent_account_selection(
                parent_options
            ).model_dump(),
        }

    new_ad_plan = dict(state["ad_plan"])
    new_ad_plan[config["parent_id_field"]] = selected_id
    selected_name = next(
        (a.get("name") for a in parent_options if str(a.get("id")) == str(selected_id)),
        selected_id,
    )

    writer(
        {
            "type": "progress",
            "node": "select_parent_account",
            "phase": "end",
            "label": f"Selected: {selected_name}",
        }
    )
    account_attachment = {
        "type": "confirmed_account",
        "name": selected_name,
        "id": selected_id,
        "account_type": "parent",
    }
    reply = f"Selected {config['parent_label']}: {selected_name}"
    return {
        "ad_plan": new_ad_plan,
        "status": ChatStatus.SELECTING_ACCOUNT,
        "response_message": reply,
        "intermediate_messages": [{"reply": reply, "attachments": [account_attachment]}],
    }


def _get_config(state: ChatState) -> dict:
    platform = state.get("ad_plan", {}).get("platform", "google")
    return PLATFORM_CONFIG[platform]
