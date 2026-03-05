"""Account Selection — fetch and select child (customer/ad) accounts."""

from typing import Any

from langgraph.config import get_stream_writer
from structlog import get_logger

from agents.chatv2 import dependencies
from agents.chatv2.platform_config import PLATFORM_CONFIG, all_fields_collected
from agents.chatv2.state import ChatState
from core.chatv2.models import ChatStatus, AccountSelection
from core.chatv2.validator import validate_account_selection
from core.infrastructure.context import auth_context

logger = get_logger(__name__)


async def fetch_account_options(state: ChatState) -> dict[str, Any]:
    """Fetch child accounts for the currently selected parent."""
    writer = get_stream_writer()
    config = _get_config(state)
    writer(
        {
            "type": "progress",
            "node": "fetch_account",
            "phase": "start",
            "label": config["progress_load_children"],
        }
    )
    parent_id = state["ad_plan"].get(config["parent_id_field"])
    parent_options = state.get("parent_account_options", [])

    if not parent_id:
        writer(
            {
                "type": "progress",
                "node": "fetch_account",
                "phase": "end",
                "label": f"No {config['parent_label']} selected",
            }
        )
        return {
            "response_message": f"Please select a {config['parent_label']} first.",
            "status": ChatStatus.SELECTING_PARENT_ACCOUNT,
            "account_selection": AccountSelection.parent_account_selection(
                parent_options
            ).model_dump()
            if parent_options
            else None,
        }

    client_code = auth_context.client_code

    try:
        children = await getattr(dependencies, config["fetch_children"])(
            parent_id, client_code
        )
    except Exception:
        logger.exception("Error fetching child accounts")
        writer(
            {
                "type": "progress",
                "node": "fetch_account",
                "phase": "end",
                "label": f"Error loading {config['account_label']}s",
            }
        )
        return {
            "response_message": f"Error fetching {config['account_label']}s.",
            "account_selection": None,
        }

    if not children:
        writer(
            {
                "type": "progress",
                "node": "fetch_account",
                "phase": "end",
                "label": f"No {config['account_label']}s found",
            }
        )
        return {
            "account_options": [],
            "status": ChatStatus.SELECTING_PARENT_ACCOUNT,
            "response_message": f"No {config['account_label']}s found. Select a different {config['parent_label']}.",
            "account_selection": AccountSelection.parent_account_selection(
                parent_options
            ).model_dump(),
        }

    if len(children) == 1:
        new_ad_plan = dict(state["ad_plan"])
        new_ad_plan[config["account_id_field"]] = children[0].get("id")
        child_name = children[0].get("name", children[0].get("id"))
        status = (
            ChatStatus.AWAITING_CONFIRMATION
            if all_fields_collected(new_ad_plan, config)
            else ChatStatus.IN_PROGRESS
        )
        writer(
            {
                "type": "progress",
                "node": "fetch_account",
                "phase": "end",
                "label": f"Auto-selected {config['account_label']}: {child_name}",
            }
        )
        return {
            "ad_plan": new_ad_plan,
            "account_options": children,
            "status": status,
            "response_message": f"Auto-selected {config['account_label']}: {child_name}",
            "account_selection": None,
        }

    writer(
        {
            "type": "progress",
            "node": "fetch_account",
            "phase": "end",
            "label": f"Found {len(children)} {config['account_label']}s",
        }
    )
    return {
        "account_options": children,
        "status": ChatStatus.SELECTING_ACCOUNT,
        "response_message": f"{config['account_label'].capitalize()}s under {config['parent_label']} {parent_id}:",
        "account_selection": AccountSelection.account_selection(children).model_dump(),
    }


async def select_account_node(state: ChatState) -> dict[str, Any]:
    """Handle child account selection from user input."""
    writer = get_stream_writer()
    config = _get_config(state)
    writer(
        {
            "type": "progress",
            "node": "select_account",
            "phase": "start",
            "label": config["progress_select_account"],
        }
    )
    messages = state.get("messages", [])
    account_options = state.get("account_options", [])

    if not messages:
        writer(
            {
                "type": "progress",
                "node": "select_account",
                "phase": "end",
                "label": f"Waiting for {config['account_label']} selection",
            }
        )
        return {
            "response_message": f"Please select a {config['account_label']}.",
            "account_selection": AccountSelection.account_selection(
                account_options
            ).model_dump(),
        }

    last_message = messages[-1]
    content = (
        last_message.content if hasattr(last_message, "content") else str(last_message)
    )
    selected_id = content.strip() if isinstance(content, str) else str(content)

    if not validate_account_selection(selected_id, account_options):
        writer(
            {
                "type": "progress",
                "node": "select_account",
                "phase": "end",
                "label": "Invalid selection",
            }
        )
        return {
            "response_message": "Invalid selection. Please choose from the list.",
            "account_selection": AccountSelection.account_selection(
                account_options
            ).model_dump(),
        }

    new_ad_plan = dict(state["ad_plan"])
    new_ad_plan[config["account_id_field"]] = selected_id

    selected_name = next(
        (
            a.get("name")
            for a in account_options
            if str(a.get("id")) == str(selected_id)
        ),
        None,
    )
    end_label = (
        f"Selected: {selected_name}"
        if selected_name
        else f"{config['account_label'].capitalize()} selected"
    )

    if all_fields_collected(new_ad_plan, config):
        writer(
            {
                "type": "progress",
                "node": "select_account",
                "phase": "end",
                "label": end_label,
            }
        )
        return {
            "ad_plan": new_ad_plan,
            "status": ChatStatus.AWAITING_CONFIRMATION,
            "account_selection": None,
        }

    writer(
        {
            "type": "progress",
            "node": "select_account",
            "phase": "end",
            "label": end_label,
        }
    )
    return {
        "ad_plan": new_ad_plan,
        "status": ChatStatus.IN_PROGRESS,
        "response_message": f"{config['account_label'].capitalize()} selected.",
        "account_selection": None,
    }


def _get_config(state: ChatState) -> dict:
    platform = state.get("ad_plan", {}).get("platform", "google")
    return PLATFORM_CONFIG[platform]
