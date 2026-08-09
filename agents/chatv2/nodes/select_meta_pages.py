"""Meta Page and Instagram account selection nodes."""

from typing import Any

from langgraph.config import get_stream_writer
from structlog import get_logger

from agents.chatv2 import dependencies
from agents.chatv2.platform_config import PLATFORM_CONFIG
from agents.chatv2.state import ChatState
from core.chatv2.models import ChatStatus, AccountType, AccountOption
from core.chatv2.validator import validate_account_selection
from core.infrastructure.context import auth_context

logger = get_logger(__name__)


async def fetch_fb_pages_options(state: ChatState) -> dict[str, Any]:
    """Fetch Facebook Page options for the selected Business Account."""
    writer = get_stream_writer()
    config = _get_config(state)
    writer(
        {
            "type": "progress",
            "node": "fetch_fb_pages",
            "phase": "start",
            "label": config.get("progress_load_fb_pages", "Loading Facebook pages"),
        }
    )
    business_id = state["ad_plan"].get(config["parent_id_field"])
    client_code = auth_context.client_code

    logger.info(
        "Fetching FB pages for business",
        business_id=business_id,
        client_code=client_code,
    )

    try:
        pages = await dependencies.fetch_fb_pages(business_id, client_code)
        logger.info(
            "Fetched FB pages result", count=len(pages) if pages else 0, pages=pages
        )
    except Exception:
        logger.exception("Error fetching FB pages")
        writer(
            {
                "type": "progress",
                "node": "fetch_fb_pages",
                "phase": "end",
                "label": "Error loading Facebook pages",
            }
        )
        return {
            "response_message": "Error fetching Facebook pages.",
            "account_selection": None,
        }

    if not pages:
        writer(
            {
                "type": "progress",
                "node": "fetch_fb_pages",
                "phase": "end",
                "label": "No Facebook pages found",
            }
        )
        return {
            "status": ChatStatus.SELECTING_PARENT_ACCOUNT,
            "response_message": "No Facebook pages found for this business. Please select a different business account.",
        }

    if len(pages) == 1:
        new_ad_plan = dict(state["ad_plan"])
        new_ad_plan[config["fb_page_id_field"]] = pages[0].get("id")
        page_name = pages[0].get("name", pages[0].get("id"))
        writer(
            {
                "type": "progress",
                "node": "fetch_fb_pages",
                "phase": "end",
                "label": f"Auto-selected page: {page_name}",
            }
        )
        # Record auto-selection if not already recorded
        auto_selected = list(state.get("auto_selected_assets", []))
        if not any(a["id"] == str(pages[0].get("id")) for a in auto_selected):
            auto_selected.append(
                {
                    "label": config["fb_page_label"],
                    "name": page_name,
                    "id": str(pages[0].get("id")),
                }
            )

        prev_msg = state.get("response_message", "")
        new_msg = f"Auto-selected Facebook page: {page_name}"
        full_msg = f"{prev_msg}\n{new_msg}".strip() if prev_msg else new_msg

        return {
            "ad_plan": new_ad_plan,
            "status": ChatStatus.SELECTING_IG_PAGE,
            "response_message": full_msg,
            "auto_selected_assets": auto_selected,
        }

    writer(
        {
            "type": "progress",
            "node": "fetch_fb_pages",
            "phase": "end",
            "label": f"Found {len(pages)} Facebook pages",
        }
    )
    return {
        "account_options": pages,
        "status": ChatStatus.SELECTING_FB_PAGE,
        "response_message": "Please select a Facebook page:",
        "account_selection": {
            "type": AccountType.FB_PAGE,
            "options": [AccountOption(**o) for o in pages],
        },
    }


async def select_fb_page_node(state: ChatState) -> dict[str, Any]:
    """Handle FB Page selection from user input."""
    writer = get_stream_writer()
    config = _get_config(state)
    writer(
        {
            "type": "progress",
            "node": "select_fb_page",
            "phase": "start",
            "label": config.get("progress_select_fb_page", "Selecting Facebook page"),
        }
    )
    messages = state.get("messages", [])
    page_options = state.get("account_options", [])

    if not messages:
        return {
            "response_message": "Please select a Facebook page.",
            "account_selection": {
                "type": AccountType.FB_PAGE,
                "options": [AccountOption(**o) for o in page_options],
            },
        }

    last_message = messages[-1]
    selected_id = (
        last_message.content.strip()
        if hasattr(last_message, "content")
        else str(last_message)
    )

    if not validate_account_selection(selected_id, page_options):
        return {
            "response_message": "Invalid selection. Please choose from the list.",
            "account_selection": {
                "type": AccountType.FB_PAGE,
                "options": [AccountOption(**o) for o in page_options],
            },
        }

    new_ad_plan = dict(state["ad_plan"])
    new_ad_plan[config["fb_page_id_field"]] = selected_id

    selected_name = next(
        (p.get("name") for p in page_options if str(p.get("id")) == str(selected_id)),
        selected_id,
    )

    # Record selection for summary
    auto_selected = list(state.get("auto_selected_assets", []))
    if not any(a["id"] == str(selected_id) for a in auto_selected):
        auto_selected.append(
            {"label": config["fb_page_label"], "name": selected_name, "id": str(selected_id)}
        )

    writer(
        {
            "type": "progress",
            "node": "select_fb_page",
            "phase": "end",
            "label": f"Selected Page: {selected_name}",
        }
    )

    return {
        "ad_plan": new_ad_plan,
        "status": ChatStatus.SELECTING_IG_PAGE,
        "response_message": f"Selected Facebook page: {selected_name}",
        "account_selection": None,
        "auto_selected_assets": auto_selected,
    }


async def fetch_ig_pages_options(state: ChatState) -> dict[str, Any]:
    """Fetch Instagram account options for the selected FB Page."""
    writer = get_stream_writer()
    config = _get_config(state)
    writer(
        {
            "type": "progress",
            "node": "fetch_ig_pages",
            "phase": "start",
            "label": config.get(
                "progress_load_ig_accounts", "Loading Instagram accounts"
            ),
        }
    )
    page_id = state["ad_plan"].get(config["fb_page_id_field"])
    client_code = auth_context.client_code
    business_id = state["ad_plan"].get(config["parent_id_field"])

    try:
        accounts = await dependencies.fetch_ig_accounts(
            page_id, client_code, business_id=business_id
        )
    except Exception:
        logger.exception("Error fetching IG accounts")
        writer(
            {
                "type": "progress",
                "node": "fetch_ig_pages",
                "phase": "end",
                "label": "Error loading Instagram accounts",
            }
        )
        return {
            "response_message": "Error fetching Instagram accounts.",
            "account_selection": None,
        }

    if not accounts:
        writer(
            {
                "type": "progress",
                "node": "fetch_ig_pages",
                "phase": "end",
                "label": "No Instagram accounts found",
            }
        )
        # Some users might not have IG linked, but usually Meta requires it for many ad types.
        # Fallback to next step if no IG found? Or error?
        # User said "instagram pages should be fetched", implying it's required.
        return {
            "status": ChatStatus.SELECTING_FB_PAGE,
            "response_message": "No Instagram accounts found linked to this page. Please select a different page or check your setup.",
        }

    if len(accounts) == 1:
        new_ad_plan = dict(state["ad_plan"])
        new_ad_plan[config["ig_page_id_field"]] = accounts[0].get("id")
        ig_name = accounts[0].get("name", accounts[0].get("id"))
        writer(
            {
                "type": "progress",
                "node": "fetch_ig_pages",
                "phase": "end",
                "label": f"Auto-selected IG: {ig_name}",
            }
        )
        # Record auto-selection if not already recorded
        auto_selected = list(state.get("auto_selected_assets", []))
        if not any(a["id"] == str(accounts[0].get("id")) for a in auto_selected):
            auto_selected.append(
                {
                    "label": config["ig_page_label"],
                    "name": ig_name,
                    "id": str(accounts[0].get("id")),
                }
            )

        prev_msg = state.get("response_message", "")
        new_msg = f"Auto-selected Instagram account: {ig_name}"
        full_msg = f"{prev_msg}\n{new_msg}".strip() if prev_msg else new_msg

        return {
            "ad_plan": new_ad_plan,
            "status": ChatStatus.SELECTING_PIXEL,
            "response_message": full_msg,
            "auto_selected_assets": auto_selected,
        }

    writer(
        {
            "type": "progress",
            "node": "fetch_ig_pages",
            "phase": "end",
            "label": f"Found {len(accounts)} Instagram accounts",
        }
    )
    return {
        "account_options": accounts,
        "status": ChatStatus.SELECTING_IG_PAGE,
        "response_message": "Please select an Instagram account:",
        "account_selection": {
            "type": AccountType.IG_ACCOUNT,
            "options": [AccountOption(**o) for o in accounts],
        },
    }


async def select_ig_page_node(state: ChatState) -> dict[str, Any]:
    """Handle IG selection from user input."""
    writer = get_stream_writer()
    config = _get_config(state)
    writer(
        {
            "type": "progress",
            "node": "select_ig_page",
            "phase": "start",
            "label": config.get(
                "progress_select_ig_account", "Selecting Instagram account"
            ),
        }
    )
    messages = state.get("messages", [])
    ig_options = state.get("account_options", [])

    if not messages:
        return {
            "response_message": "Please select an Instagram account.",
            "account_selection": {
                "type": AccountType.IG_ACCOUNT,
                "options": [AccountOption(**o) for o in ig_options],
            },
        }

    last_message = messages[-1]
    selected_id = (
        last_message.content.strip()
        if hasattr(last_message, "content")
        else str(last_message)
    )

    if not validate_account_selection(selected_id, ig_options):
        return {
            "response_message": "Invalid selection. Please choose from the list.",
            "account_selection": {
                "type": AccountType.IG_ACCOUNT,
                "options": [AccountOption(**o) for o in ig_options],
            },
        }

    new_ad_plan = dict(state["ad_plan"])
    new_ad_plan[config["ig_page_id_field"]] = selected_id

    selected_name = next(
        (a.get("name") for a in ig_options if str(a.get("id")) == str(selected_id)),
        selected_id,
    )

    # Record selection for summary
    auto_selected = list(state.get("auto_selected_assets", []))
    if not any(a["id"] == str(selected_id) for a in auto_selected):
        auto_selected.append(
            {"label": config["ig_page_label"], "name": selected_name, "id": str(selected_id)}
        )

    writer(
        {
            "type": "progress",
            "node": "select_ig_page",
            "phase": "end",
            "label": f"Selected IG: {selected_name}",
        }
    )

    return {
        "ad_plan": new_ad_plan,
        "status": ChatStatus.SELECTING_PIXEL,
        "response_message": f"Selected Instagram account: {selected_name}",
        "account_selection": None,
        "auto_selected_assets": auto_selected,
    }


def _get_config(state: ChatState) -> dict:
    platform = state.get("ad_plan", {}).get("platform", "google")
    return PLATFORM_CONFIG[platform]
