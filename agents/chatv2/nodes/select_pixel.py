"""Select Pixel Node - Handles Meta Pixel selection."""

from typing import Any
from langgraph.config import get_stream_writer
from structlog import get_logger

from agents.chatv2.platform_config import PLATFORM_CONFIG
from agents.chatv2.state import ChatState
from core.chatv2.models import AccountSelection, ChatStatus
from core.infrastructure.context import auth_context
from agents.chatv2.dependencies import fetch_pixels

logger = get_logger(__name__)


async def fetch_pixel_options(state: ChatState) -> dict[str, Any]:
    """Fetch Meta pixels for the selected ad account."""
    writer = get_stream_writer()
    ad_plan = dict(state["ad_plan"])
    platform = ad_plan.get("platform")
    config = PLATFORM_CONFIG.get(platform, {})

    writer(
        {
            "type": "progress",
            "node": "fetch_pixel_options",
            "phase": "start",
            "label": config.get("progress_load_pixels", "Loading pixels"),
        }
    )

    ad_account_id = ad_plan.get(config.get("account_id_field"))
    if not ad_account_id:
        logger.error("No ad account selected for pixel fetching")
        return {"status": ChatStatus.SELECTING_ACCOUNT}

    client_code = auth_context.client_code

    try:
        pixels = await fetch_pixels(
            ad_account_id=ad_account_id,
            client_code=client_code,
        )
    except Exception as e:
        logger.error("Failed to fetch pixels from ad account", error=str(e))
        pixels = []

    # Fallback to business level if no pixels found at account level
    if not pixels:
        business_id = ad_plan.get(config.get("parent_id_field"))
        if business_id:
            logger.info(
                "Trying fallback to business level pixels", business_id=business_id
            )
            try:
                from agents.chatv2.dependencies import fetch_business_pixels

                pixels = await fetch_business_pixels(
                    business_id=business_id,
                    client_code=client_code,
                )
            except Exception as e:
                logger.error(
                    "Failed to fetch pixels from business account", error=str(e)
                )
                pixels = []

    writer(
        {
            "type": "progress",
            "node": "fetch_pixel_options",
            "phase": "end",
            "label": f"Found {len(pixels)} pixels",
        }
    )

    if not pixels:
        logger.warning(
            "No pixels found for ad account or business", ad_account_id=ad_account_id
        )
        # Fallback: Proceed to confirmation if no pixels found
        return {
            "status": ChatStatus.AWAITING_CONFIRMATION,
            "account_options": [],
        }

    logger.info("Fetched pixels", count=len(pixels), ad_account_id=ad_account_id)

    # Record options for the frontend
    if len(pixels) == 1:
        # Auto-select if only one pixel
        pixel = pixels[0]
        pixel_id = str(pixel["id"])
        pixel_name = pixel["name"]

        new_ad_plan = dict(ad_plan)
        new_ad_plan[config["pixel_id_field"]] = pixel_id

        auto_selected = list(state.get("auto_selected_assets", []))
        if not any(a["id"] == pixel_id for a in auto_selected):
            auto_selected.append(
                {
                    "label": config.get("pixel_label", "Pixel"),
                    "name": pixel_name,
                    "id": pixel_id,
                }
            )

        prev_msg = state.get("response_message", "")
        new_msg = f"Auto-selected Meta pixel: {pixel_name}"
        full_msg = f"{prev_msg}\n{new_msg}".strip() if prev_msg else new_msg

        return {
            "ad_plan": new_ad_plan,
            "account_options": pixels,
            "status": ChatStatus.AWAITING_CONFIRMATION,
            "response_message": full_msg,
            "auto_selected_assets": auto_selected,
        }

    return {
        "account_options": pixels,
        "status": ChatStatus.SELECTING_PIXEL,
        "response_message": f"Please select your {config.get('pixel_label', 'pixel')}:",
        "account_selection": AccountSelection.pixel_selection(pixels).model_dump(),
    }


async def select_pixel_node(state: ChatState) -> dict[str, Any]:
    """Handle user pixel selection."""
    writer = get_stream_writer()
    ad_plan = dict(state["ad_plan"])
    platform = ad_plan.get("platform", "meta")
    config = PLATFORM_CONFIG.get(platform, {})

    writer(
        {
            "type": "progress",
            "node": "select_pixel",
            "phase": "start",
            "label": config.get("progress_select_pixel", "Selecting Meta pixel"),
        }
    )

    messages = state.get("messages", [])
    pixel_options = state.get("account_options", [])

    if not messages:
        return {
            "status": ChatStatus.SELECTING_PIXEL,
            "response_message": f"Please select your {config.get('pixel_label', 'pixel')}:",
            "account_selection": AccountSelection.pixel_selection(
                pixel_options
            ).model_dump(),
        }

    last_message = messages[-1]
    content = (
        last_message.content if hasattr(last_message, "content") else str(last_message)
    )
    selected_id = content.strip() if isinstance(content, str) else str(content)

    # Simple validation — check if the ID exists in the fetched pixels
    selected_pixel = next(
        (p for p in pixel_options if str(p.get("id")) == selected_id), None
    )

    if not selected_pixel:
        writer(
            {
                "type": "progress",
                "node": "select_pixel",
                "phase": "end",
                "label": "Invalid pixel selection",
            }
        )
        return {
            "status": ChatStatus.SELECTING_PIXEL,
            "response_message": f"Invalid selection. Please choose a {config.get('pixel_label', 'pixel')} from the list:",
            "account_selection": AccountSelection.pixel_selection(
                pixel_options
            ).model_dump(),
        }

    pixel_id = str(selected_pixel["id"])
    pixel_name = selected_pixel["name"]

    new_ad_plan = dict(ad_plan)
    new_ad_plan[config["pixel_id_field"]] = pixel_id

    # Record selection for summary
    auto_selected = list(state.get("auto_selected_assets", []))
    if not any(a["id"] == str(pixel_id) for a in auto_selected):
        auto_selected.append(
            {"label": config["pixel_label"], "name": pixel_name, "id": str(pixel_id)}
        )

    writer(
        {
            "type": "progress",
            "node": "select_pixel",
            "phase": "end",
            "label": f"Selected pixel: {pixel_name}",
        }
    )

    return {
        "ad_plan": new_ad_plan,
        "status": ChatStatus.AWAITING_CONFIRMATION,
        "response_message": f"Pixel selected: {pixel_name}",
        "account_selection": None,
        "auto_selected_assets": auto_selected,
    }
