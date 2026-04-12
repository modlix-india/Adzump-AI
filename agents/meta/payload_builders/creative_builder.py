from agents.meta.utils.payload_helpers import build_name
from core.models.meta import (
    CreativePayload,
    DestinationType,
    AdCreationStage,
    CreativeType,
    CreativeFormat,
)


def build_creative_payload(creative: CreativePayload, is_dynamic: bool) -> dict:
    """
    Routes to the correct builder based on creative type and dynamic flag.
    Validation is handled by Pydantic models centrally.
    """
    creative_dict = creative.model_dump(mode="json", exclude_none=True)
    creative_type = creative_dict.get("type")
    destination_type = creative.destination_type

    if is_dynamic and destination_type == DestinationType.ON_AD:
        return _build_automatic_creative(creative_dict, destination_type)

    if creative_type == CreativeType.IMAGE:
        if is_dynamic:
            return _build_dynamic_image_creative(creative_dict, destination_type)
        else:
            return _build_non_dynamic_image_creative(creative_dict, destination_type)

    # VIDEO and CAROUSEL — extendable here
    return {}


def _build_automatic_creative(creative: dict, destination_type: str) -> dict:
    """
    Automatic (dynamic) creative builder.
    Currently supports image-based dynamic creatives.
    """

    call_to_action = creative.get("call_to_action", {})

    asset_feed = {
        "ad_formats": [CreativeFormat.AUTOMATIC_FORMAT],
        "bodies": [{"text": t} for t in creative.get("primary_texts", [])],
        "titles": [{"text": t} for t in creative.get("headlines", [])],
        "images": [{"hash": h} for h in creative.get("image_hashes", [])],
        "link_urls": [{"website_url": call_to_action.get("url", "")}],
        "call_to_action_types": [call_to_action.get("type")],
    }

    if creative.get("descriptions"):
        asset_feed["descriptions"] = [
            {"text": d} for d in creative.get("descriptions", [])
        ]

    if destination_type == DestinationType.ON_AD:
        asset_feed["call_to_actions"] = [
            {
                "type": call_to_action.get("type"),
                "value": {"lead_gen_form_id": call_to_action.get("lead_gen_form_id")},
            }
        ]

    object_story_spec = {
        "page_id": creative.get("page_id"),
    }

    if creative.get("instagram_user_id"):
        object_story_spec["instagram_user_id"] = creative.get("instagram_user_id")

    payload = {
        "name": build_name(creative.get("name"), AdCreationStage.CREATIVE),
        "object_story_spec": object_story_spec,
        "asset_feed_spec": asset_feed,
    }

    if creative.get("url_tags"):
        payload["url_tags"] = creative.get("url_tags").strip()

    return payload


def _build_dynamic_image_creative(creative: dict, destination_type: str) -> dict:
    """
    Builds Meta asset_feed_spec for dynamic image creative.
    Multiple texts, headlines, images — Meta picks the best combination.
    """
    call_to_action = creative.get("call_to_action", {})

    asset_feed = {
        "ad_formats": [CreativeFormat.SINGLE_IMAGE],
        "bodies": [{"text": text} for text in creative.get("primary_texts", [])],
        "titles": [{"text": text} for text in creative.get("headlines", [])],
        "images": [{"hash": hash_id} for hash_id in creative.get("image_hashes", [])],
        "link_urls": [{"website_url": call_to_action.get("url", "")}],
        "call_to_action_types": [call_to_action.get("type", "")],
    }

    if creative.get("descriptions"):
        asset_feed["descriptions"] = [
            {"text": desc} for desc in creative["descriptions"]
        ]

    name = build_name(creative.get("name"), AdCreationStage.CREATIVE)

    object_story_spec = {"page_id": creative.get("page_id")}

    if creative.get("instagram_user_id"):
        object_story_spec["instagram_user_id"] = creative.get("instagram_user_id")

    payload = {
        "name": name,
        "object_story_spec": object_story_spec,
        "asset_feed_spec": asset_feed,
    }

    if creative.get("url_tags"):
        payload["url_tags"] = creative.get("url_tags").strip()

    return payload


def _build_non_dynamic_image_creative(creative: dict, destination_type: str) -> dict:
    """
    Builds Meta object_story_spec for standard single image creative.
    Uses only first text, headline, image.
    """
    call_to_action = creative.get("call_to_action", {})
    object_story_spec = {"page_id": creative.get("page_id")}

    if creative.get("instagram_user_id"):
        object_story_spec["instagram_user_id"] = creative.get("instagram_user_id")

    primary_texts = creative.get("primary_texts")
    headlines = creative.get("headlines")
    image_hashes = creative.get("image_hashes")

    link_data = {
        "message": primary_texts[0],
        "name": headlines[0],
        "image_hash": image_hashes[0],
    }

    if destination_type == DestinationType.ON_AD:
        link_data["link"] = "http://fb.me/"
        link_data["call_to_action"] = {
            "type": call_to_action.get("type"),
            "value": {"lead_gen_form_id": call_to_action.get("lead_gen_form_id")},
        }
    else:
        link_data["link"] = call_to_action.get("url")
        link_data["call_to_action"] = {
            "type": call_to_action.get("type"),
            "value": {"link": call_to_action.get("url")},
        }

    descriptions = creative.get("descriptions")
    if descriptions:
        link_data["description"] = descriptions[0]

    object_story_spec = {
        "page_id": creative.get("page_id"),
        "link_data": {k: v for k, v in link_data.items() if v is not None},
    }

    if destination_type == DestinationType.ON_AD and creative.get("instagram_user_id"):
        object_story_spec["instagram_user_id"] = creative.get("instagram_user_id")

    name = build_name(creative.get("name"), AdCreationStage.CREATIVE)
    payload = {
        "name": name,
        "object_story_spec": object_story_spec,
    }

    if creative.get("url_tags"):
        payload["url_tags"] = creative["url_tags"].strip()

    return payload
