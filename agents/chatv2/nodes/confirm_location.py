"""Location Confirmation Node - Map-based location confirmation for real estate businesses."""

import asyncio
import json
import os
from typing import Any, Optional
from urllib.parse import quote

from langchain_core.messages import AIMessage
from langgraph.config import get_config, get_stream_writer
from structlog import get_logger

from agents.chatv2.scrape_manager import get_scrape_task_manager
from agents.chatv2.state import ChatState
from core.chatv2.models import ChatStatus, LocationSelection
from models.business_model import WebsiteSummaryResponse

logger = get_logger(__name__)

REAL_ESTATE_TYPE = "real estate"
SCRAPE_WAIT_TIMEOUT = 45.0


async def confirm_location_node(state: ChatState) -> dict[str, Any]:
    """Confirm or collect property location for real estate businesses.

    First entry (from collect_data): check scrape result, show map if real estate.
    Re-entry (user responding): accept confirmation or corrected coordinates.
    """
    writer = get_stream_writer()
    session_id = get_config()["configurable"]["thread_id"]
    status = state.get("status", ChatStatus.IN_PROGRESS)

    if status == ChatStatus.CONFIRMING_LOCATION:
        return await _handle_user_response(state, session_id, writer)

    return await _handle_first_entry(state, session_id, writer)


async def _handle_first_entry(
    state: ChatState, session_id: str, writer: Any
) -> dict[str, Any]:
    """Check scrape result and present map if real estate, otherwise passthrough."""
    writer(
        {
            "type": "progress",
            "node": "confirm_location",
            "phase": "start",
            "label": "Checking business location",
        }
    )

    scrape_result = await _wait_for_scrape(session_id)

    if not scrape_result or not _is_real_estate(scrape_result):
        return {}

    ad_plan = dict(state.get("ad_plan") or {})
    ad_plan["businessType"] = scrape_result.business_type

    location = scrape_result.location
    location_found = bool(
        location
        and (location.product_coordinates or location.product_location)
    )

    location_data = LocationSelection(
        product_location=location.product_location if location else None,
        coordinates=location.product_coordinates if location else None,
        area_location=location.area_location if location else None,
        map_url=_build_map_embed_url(location.product_coordinates if location else None),
        location_found=location_found,
    )

    if location_found and location:
        display_name = location.product_location or location.area_location or "detected location"
        reply = (
            f"We found your property location at **{display_name}**. "
            "Please confirm this location or adjust it on the map."
        )
    else:
        reply = (
            "We couldn't detect a property location from your website. "
            "Please pin your property location on the map."
        )

    writer(
        {
            "type": "progress",
            "node": "confirm_location",
            "phase": "end",
            "label": "Location review",
        }
    )

    return {
        "status": ChatStatus.CONFIRMING_LOCATION,
        "response_message": reply,
        "messages": [AIMessage(content=reply)],
        "ad_plan": ad_plan,
        "location_selection": location_data.model_dump(),
    }


async def _handle_user_response(
    state: ChatState, session_id: str, writer: Any
) -> dict[str, Any]:
    """Process user's location confirmation or correction."""
    writer(
        {
            "type": "progress",
            "node": "confirm_location",
            "phase": "start",
            "label": "Processing location",
        }
    )

    last_message = _get_last_user_message(state)
    coordinates = _try_parse_location_data(last_message)
    ad_plan = dict(state.get("ad_plan") or {})

    if coordinates:
        geo_targets = await _resolve_geo_targets(coordinates)
        ad_plan["location"] = {
            "coordinates": coordinates,
            "product_location": None,
            "area_location": None,
            "geo_targets": geo_targets,
        }
        reply = f"Location saved ({coordinates['lat']:.4f}, {coordinates['lng']:.4f}). Now setting up your ad accounts."
    else:
        existing_selection = state.get("location_selection") or {}
        ad_plan["location"] = {
            "coordinates": existing_selection.get("coordinates"),
            "product_location": existing_selection.get("product_location"),
            "area_location": existing_selection.get("area_location"),
            "geo_targets": await _resolve_geo_targets(
                existing_selection.get("coordinates")
            ),
        }
        loc_name = existing_selection.get("product_location") or existing_selection.get("area_location") or "your location"
        reply = f"Location confirmed: {loc_name}. Now setting up your ad accounts."

    location = ad_plan.get("location", {})
    attachment = {
        "type": "confirmed_location",
        "label": location.get("product_location")
            or location.get("area_location")
            or "Selected location",
    }
    if location.get("coordinates"):
        attachment["coordinates"] = location["coordinates"]

    return {
        "status": ChatStatus.SELECTING_PARENT_ACCOUNT,
        "response_message": reply,
        "messages": [AIMessage(content=reply)],
        "ad_plan": ad_plan,
        "location_selection": None,
        "intermediate_messages": [{"reply": reply, "attachments": [attachment]}],
    }


async def _wait_for_scrape(
    session_id: str,
) -> Optional[WebsiteSummaryResponse]:
    """Wait for background scrape to complete with timeout."""
    manager = get_scrape_task_manager()
    elapsed = 0.0
    while elapsed < SCRAPE_WAIT_TIMEOUT:
        result = manager.get_result_if_ready(session_id)
        if result:
            return result
        if manager.get_error(session_id):
            return None
        if not manager.has_active_scrape(session_id):
            return None
        await asyncio.sleep(1.0)
        elapsed += 1.0
    logger.warning("scrape_wait_timeout", session_id=session_id)
    return None


def _is_real_estate(result: WebsiteSummaryResponse) -> bool:
    """Check if the scraped business is in the real estate category."""
    if not result.business_type:
        return False
    return REAL_ESTATE_TYPE in result.business_type.strip().lower()


def _get_last_user_message(state: ChatState) -> str:
    """Extract text from the last human message."""
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "type") and msg.type == "human":
            content = msg.content
            return content if isinstance(content, str) else ""
    return ""


def _try_parse_location_data(message: str) -> Optional[dict]:
    """Try to parse JSON location data from user message.

    Expected format: {"type": "location_update", "lat": 12.97, "lng": 77.59}
    """
    try:
        parsed = json.loads(message)
        if isinstance(parsed, dict) and parsed.get("type") == "location_update":
            lat = parsed.get("lat")
            lng = parsed.get("lng")
            if lat is not None and lng is not None:
                return {"lat": float(lat), "lng": float(lng)}
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


async def _resolve_geo_targets(
    coordinates: Optional[dict],
) -> list[dict]:
    """Resolve coordinates to Google Ads geo targets."""
    if not coordinates:
        return []
    try:
        from core.infrastructure.context import get_auth_context
        from services.geo_target_service import GeoTargetService

        auth = get_auth_context()
        geo_service = GeoTargetService(client_code=auth.client_code)
        result = await geo_service.suggest_geo_targets(coordinates=coordinates)
        return [loc.model_dump() for loc in result.locations]
    except Exception as e:
        logger.warning("geo_target_resolution_failed", error=str(e))
        return []


def _build_map_embed_url(coordinates: Optional[dict]) -> Optional[str]:
    """Build a Google Maps embed URL for the given coordinates."""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return None

    if coordinates and "lat" in coordinates and "lng" in coordinates:
        lat, lng = coordinates["lat"], coordinates["lng"]
        return (
            f"https://www.google.com/maps/embed/v1/place"
            f"?key={api_key}"
            f"&q={lat},{lng}"
            f"&zoom=15"
        )
    return (
        f"https://www.google.com/maps/embed/v1/view"
        f"?key={api_key}"
        f"&center=20.5937,78.9629"
        f"&zoom=5"
    )
