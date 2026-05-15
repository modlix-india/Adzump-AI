import structlog
from typing import Any
from core.models.meta import (
    CreativePayload,
    DestinationType,
    CreativeMode,
    CreativeType,
    AdCreationStage,
)
from agents.meta.utils.payload_helpers import build_name

logger = structlog.get_logger(__name__)


def build_creative_payload(creative: CreativePayload, is_dynamic: bool) -> dict:
    """Entry point for building Meta Ad Creative payloads."""
    mode = creative.mode or (
        CreativeMode.DYNAMIC if is_dynamic else CreativeMode.STANDARD
    )

    # Route to the appropriate builder based on Type and Mode
    builder_func = BUILDER_REGISTRY.get((creative.type, mode))

    if not builder_func:
        builder_func = BUILDER_REGISTRY.get((creative.type, CreativeMode.STANDARD))

    if not builder_func:
        raise ValueError(
            f"No builder found for Creative Type: {creative.type} and Mode: {mode}"
        )

    payload = builder_func(creative)

    # Root-level URL tags for tracking
    if creative.url_tags:
        payload["url_tags"] = creative.url_tags

    return payload


# --- Standard Builders (1-to-1) ---


def _build_standard_image(creative: CreativePayload) -> dict:
    """Build a standard single image creative payload (1-to-1)."""
    spec = _get_base_spec(creative)
    cta_payload = _get_cta_payload(creative)

    spec["link_data"] = {
        "image_hash": creative.image_hashes[0],
        "link": cta_payload["value"].get("link", "http://fb.me/"),
        "message": creative.primary_texts[0],
        "call_to_action": cta_payload,
        "name": creative.headlines[0],
    }
    if creative.descriptions:
        spec["link_data"]["description"] = creative.descriptions[0]

    return {
        "name": build_name(creative.name, AdCreationStage.CREATIVE),
        "object_story_spec": spec,
    }


def _build_standard_video(creative: CreativePayload) -> dict:
    """Build a standard single video creative payload."""
    spec = _get_base_spec(creative)
    cta_payload = _get_cta_payload(creative)

    video_id = creative.video_ids[0] if creative.video_ids else None

    # Use first thumbnail from list
    image_url = creative.thumbnail_urls[0] if creative.thumbnail_urls else None

    spec["video_data"] = {
        "video_id": video_id,
        "link_description": (
            creative.descriptions[0] if creative.descriptions else None
        ),
        "message": creative.primary_texts[0],
        "call_to_action": cta_payload,
        "title": creative.headlines[0],
        "image_url": image_url,
    }

    return {
        "name": build_name(creative.name, AdCreationStage.CREATIVE),
        "object_story_spec": spec,
    }


def _build_standard_carousel(creative: CreativePayload) -> dict:
    """Standard carousel builder (child_attachments). Supports both images and videos."""
    child_attachments = []
    logger.info(
        "Building standard carousel",
        type=creative.type,
        mode=creative.mode,
        num_images=len(creative.image_hashes),
        num_videos=len(creative.video_ids),
    )

    # 1. Build Image Cards
    for i, image_hash in enumerate(creative.image_hashes):
        headline = creative.headlines[min(i, len(creative.headlines) - 1)]
        description = (
            creative.descriptions[min(i, len(creative.descriptions) - 1)]
            if creative.descriptions
            else None
        )
        card_link = (
            "http://fb.me/"
            if creative.destination_type == DestinationType.ON_AD
            else creative.call_to_action.url
        )
        card_cta = _get_cta_payload(creative, card_link)

        card = {
            "name": headline,
            "image_hash": image_hash,
            "link": card_link,
            "call_to_action": card_cta,
        }
        if description:
            card["description"] = description
        child_attachments.append(card)

    # 2. Build Video Cards
    start_idx = len(child_attachments)
    for i, video_id in enumerate(creative.video_ids):
        global_idx = start_idx + i
        headline = creative.headlines[min(global_idx, len(creative.headlines) - 1)]
        description = (
            creative.descriptions[min(global_idx, len(creative.descriptions) - 1)]
            if creative.descriptions
            else None
        )
        card_link = (
            "http://fb.me/"
            if creative.destination_type == DestinationType.ON_AD
            else creative.call_to_action.url
        )
        card_cta = _get_cta_payload(creative, card_link)

        card = {
            "name": headline,
            "video_id": video_id,
            "link": card_link,
            "call_to_action": card_cta,
        }
        # Add thumbnail if available (pair by index)
        if creative.thumbnail_urls and i < len(creative.thumbnail_urls):
            card["picture"] = creative.thumbnail_urls[i]

        if description:
            card["description"] = description
        child_attachments.append(card)

    if not child_attachments:
        raise ValueError(
            "Carousel creative must have at least one image_hash or video_id."
        )

    spec = _get_base_spec(creative)
    link_data = {
        "message": creative.primary_texts[0],
        "link": child_attachments[0]["link"],
        "child_attachments": child_attachments,
        "multi_share_optimized": True,
    }

    # Meta requires a root-level image/picture for carousel preview/fallback.
    # If not provided, it's often inferred from the first card, but we can set it explicitly if needed.
    if creative.image_hashes:
        link_data["image_hash"] = creative.image_hashes[0]

    spec["link_data"] = link_data

    return {
        "name": build_name(creative.name, AdCreationStage.CREATIVE),
        "object_story_spec": spec,
    }


# --- Multi-Media Builder (Flexible Format for Non-Dynamic AdSets) ---


def _build_flexible_creative(creative: CreativePayload) -> dict:
    """
    Build the Multi-Media Creative payload using media_sourcing_spec.
    Correct approach for is_dynamic_creative=False.
    """
    cta_payload = _get_cta_payload(creative)
    spec = _get_base_spec(creative)

    # Base "Preview" spec
    base_link_data = {
        "link": cta_payload["value"].get("link", "http://fb.me/"),
        "call_to_action": cta_payload,
        "message": creative.primary_texts[0],
        "name": creative.headlines[0],
    }

    if creative.image_hashes:
        base_link_data["image_hash"] = creative.image_hashes[0]
        spec["link_data"] = base_link_data
    elif creative.video_ids:
        image_url = creative.thumbnail_urls[0] if creative.thumbnail_urls else None
        spec["video_data"] = {
            "video_id": creative.video_ids[0],
            "image_url": image_url,
            "call_to_action": cta_payload,
            "message": creative.primary_texts[0],
            "title": creative.headlines[0],
        }

    # The Flexible Rotation Pool
    media_sourcing = {
        "titles": [{"text": t} for t in creative.headlines],
        "bodies": [{"text": t} for t in creative.primary_texts],
    }

    if creative.descriptions:
        media_sourcing["descriptions"] = [{"text": d} for d in creative.descriptions]

    if creative.image_hashes:
        media_sourcing["images"] = [
            {"hash": h, "source": "multi_media", "opt_in_status": "opt_in"}
            for h in creative.image_hashes
        ]

    if creative.video_ids:
        media_sourcing["videos"] = []
        for i, vid in enumerate(creative.video_ids):
            video_entry = {
                "video_id": vid,
                "source": "multi_media",
                "opt_in_status": "opt_in",
            }
            # Add thumbnail if available (pair by index)
            if creative.thumbnail_urls and i < len(creative.thumbnail_urls):
                video_entry["thumbnail_url"] = creative.thumbnail_urls[i]

            media_sourcing["videos"].append(video_entry)

    return {
        "name": build_name(creative.name, AdCreationStage.CREATIVE),
        "object_story_spec": spec,
        "media_sourcing_spec": media_sourcing,
    }


# --- Dynamic Builder (Legacy Dynamic for is_dynamic_creative=True AdSets) ---


def _build_dynamic_creative(creative: CreativePayload) -> dict:
    """
    Build the Legacy Dynamic Creative payload using asset_feed_spec.
    Correct approach for is_dynamic_creative=True.
    Handles Single Image, Single Video, and Carousel formats.
    """
    cta = creative.call_to_action

    asset_feed = {
        "optimization_type": "REGULAR",
        "bodies": [{"text": t} for t in creative.primary_texts],
        "titles": [{"text": t} for t in creative.headlines],
        "call_to_action_types": [cta.type.value],
        "link_urls": [{"website_url": cta.url or "https://fb.me/"}],
    }

    # Hybrid CTA for Lead Gen
    if creative.destination_type == DestinationType.ON_AD:
        asset_feed["call_to_actions"] = [_get_cta_payload(creative)]

    if creative.descriptions:
        asset_feed["descriptions"] = [{"text": d} for d in creative.descriptions]

    # Format Detection
    if creative.type == CreativeType.CAROUSEL:
        if creative.image_hashes:
            asset_feed["images"] = [{"hash": h} for h in creative.image_hashes]
            asset_feed["ad_formats"] = ["CAROUSEL_IMAGE"]
        elif creative.video_ids:
            asset_feed["videos"] = []
            for i, vid in enumerate(creative.video_ids):
                video_entry = {"video_id": vid}
                if creative.thumbnail_urls and i < len(creative.thumbnail_urls):
                    video_entry["thumbnail_url"] = creative.thumbnail_urls[i]
                asset_feed["videos"].append(video_entry)
            asset_feed["ad_formats"] = ["CAROUSEL_VIDEO"]
    elif creative.image_hashes:
        asset_feed["images"] = [{"hash": h} for h in creative.image_hashes]
        asset_feed["ad_formats"] = ["SINGLE_IMAGE"]
    elif creative.video_ids:
        asset_feed["videos"] = []
        for i, vid in enumerate(creative.video_ids):
            video_entry = {"video_id": vid}

            # Pair with thumbnail if available (pair by index)
            if creative.thumbnail_urls and i < len(creative.thumbnail_urls):
                video_entry["thumbnail_url"] = creative.thumbnail_urls[i]

            asset_feed["videos"].append(video_entry)

        asset_feed["ad_formats"] = ["SINGLE_VIDEO"]

    return {
        "name": build_name(creative.name, AdCreationStage.CREATIVE),
        "object_story_spec": _get_base_spec(creative),
        "asset_feed_spec": asset_feed,
    }


# --- Shared Helpers ---


def _get_base_spec(creative: CreativePayload) -> dict:
    spec = {"page_id": creative.page_id}
    insta_id = getattr(creative, "instagram_actor_id", None) or getattr(
        creative, "instagram_user_id", None
    )
    if insta_id:
        spec["instagram_actor_id"] = insta_id
    return spec


def _get_cta_payload(creative: CreativePayload, card_link: str = None) -> dict:
    cta = creative.call_to_action
    link = card_link or cta.url or "http://fb.me/"

    if creative.destination_type == DestinationType.ON_AD:
        return {
            "type": cta.type.value,
            "value": {"lead_gen_form_id": cta.lead_gen_form_id},
        }
    else:
        return {
            "type": cta.type.value,
            "value": {"link": link},
        }


# Registry
BUILDER_REGISTRY = {
    (CreativeType.IMAGE, CreativeMode.STANDARD): _build_standard_image,
    (CreativeType.VIDEO, CreativeMode.STANDARD): _build_standard_video,
    (CreativeType.CAROUSEL, CreativeMode.STANDARD): _build_standard_carousel,
    (CreativeType.IMAGE, CreativeMode.FLEXIBLE): _build_flexible_creative,
    (CreativeType.VIDEO, CreativeMode.FLEXIBLE): _build_flexible_creative,
    (CreativeType.CAROUSEL, CreativeMode.FLEXIBLE): _build_standard_carousel,
    (CreativeType.IMAGE, CreativeMode.DYNAMIC): _build_dynamic_creative,
    (CreativeType.VIDEO, CreativeMode.DYNAMIC): _build_dynamic_creative,
    (CreativeType.CAROUSEL, CreativeMode.DYNAMIC): _build_dynamic_creative,
}
