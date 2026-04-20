from agents.meta.utils.payload_helpers import build_name
from core.models.meta import (
    CreativePayload,
    DestinationType,
    AdCreationStage,
    CreativeType,
    CreativeFormat,
)


def build_creative_payload(creative: CreativePayload, is_dynamic: bool) -> dict:
    """Route to the correct builder based on creative type and dynamic flag."""
    creative_type = creative.type
    destination_type = creative.destination_type

    if is_dynamic and destination_type == DestinationType.ON_AD:
        return _build_automatic_creative(creative, destination_type)

    if creative_type == CreativeType.IMAGE:
        if is_dynamic:
            return _build_dynamic_image_creative(creative, destination_type)
        else:
            return _build_non_dynamic_image_creative(creative, destination_type)

    raise NotImplementedError(
        f"Creative type '{creative_type.value}' is not yet supported. "
        f"Supported types: {CreativeType.IMAGE.value}"
    )


def _build_automatic_creative(creative: CreativePayload, destination_type: DestinationType) -> dict:
    """Build an automatic (dynamic) creative payload, currently optimized for lead gen (ON_AD)."""
    call_to_action = creative.call_to_action

    asset_feed = {
        "ad_formats": [CreativeFormat.AUTOMATIC_FORMAT],
        "bodies": [{"text": t} for t in creative.primary_texts],
        "titles": [{"text": t} for t in creative.headlines],
        "images": [{"hash": h} for h in creative.image_hashes],
        "link_urls": [{"website_url": call_to_action.url}],
        "call_to_action_types": [call_to_action.type.value],
    }

    if creative.descriptions:
        asset_feed["descriptions"] = [{"text": d} for d in creative.descriptions]

    if destination_type == DestinationType.ON_AD:
        asset_feed["call_to_actions"] = [
            {
                "type": call_to_action.type.value,
                "value": {"lead_gen_form_id": call_to_action.lead_gen_form_id},
            }
        ]

    object_story_spec = {"page_id": creative.page_id}
    if creative.instagram_user_id:
        object_story_spec["instagram_user_id"] = creative.instagram_user_id

    payload = {
        "name": build_name(creative.name, AdCreationStage.CREATIVE),
        "object_story_spec": object_story_spec,
        "asset_feed_spec": asset_feed,
    }

    if hasattr(creative, "url_tags") and creative.url_tags:
        payload["url_tags"] = creative.url_tags.strip()

    return payload


def _build_dynamic_image_creative(
    creative: CreativePayload, destination_type: DestinationType
) -> dict:
    """Build a dynamic image creative using Meta's asset_feed_spec for automated combinations."""
    call_to_action = creative.call_to_action

    asset_feed = {
        "ad_formats": [CreativeFormat.SINGLE_IMAGE],
        "bodies": [{"text": text} for text in creative.primary_texts],
        "titles": [{"text": text} for text in creative.headlines],
        "images": [{"hash": hash_id} for hash_id in creative.image_hashes],
        "link_urls": [{"website_url": call_to_action.url}],
        "call_to_action_types": [call_to_action.type.value],
    }

    if creative.descriptions:
        asset_feed["descriptions"] = [{"text": desc} for desc in creative.descriptions]

    object_story_spec = {"page_id": creative.page_id}
    if creative.instagram_user_id:
        object_story_spec["instagram_user_id"] = creative.instagram_user_id

    payload = {
        "name": build_name(creative.name, AdCreationStage.CREATIVE),
        "object_story_spec": object_story_spec,
        "asset_feed_spec": asset_feed,
    }

    if hasattr(creative, "url_tags") and creative.url_tags:
        payload["url_tags"] = creative.url_tags.strip()

    return payload


def _build_non_dynamic_image_creative(
    creative: CreativePayload, destination_type: DestinationType
) -> dict:
    """Build a standard single-image creative using Meta's object_story_spec."""
    primary_texts = creative.primary_texts
    headlines = creative.headlines
    image_hashes = creative.image_hashes
    call_to_action = creative.call_to_action

    # Data Integrity: Safeguard against empty lists before indexing [0]
    link_data = {
        "message": primary_texts[0] if primary_texts else None,
        "name": headlines[0] if headlines else None,
        "image_hash": image_hashes[0] if image_hashes else None,
    }

    if destination_type == DestinationType.ON_AD:
        # Intentional internal placeholder for Lead Gen
        link_data["link"] = "http://fb.me/"
        link_data["call_to_action"] = {
            "type": call_to_action.type.value,
            "value": {"lead_gen_form_id": call_to_action.lead_gen_form_id},
        }
    else:
        link_data["link"] = call_to_action.url
        link_data["call_to_action"] = {
            "type": call_to_action.type.value,
            "value": {"link": call_to_action.url},
        }

    if creative.descriptions:
        link_data["description"] = creative.descriptions[0]

    object_story_spec = {
        "page_id": creative.page_id,
        "link_data": {k: v for k, v in link_data.items() if v is not None},
    }

    if creative.instagram_user_id:
        object_story_spec["instagram_user_id"] = creative.instagram_user_id

    payload = {
        "name": build_name(creative.name, AdCreationStage.CREATIVE),
        "object_story_spec": object_story_spec,
    }

    if hasattr(creative, "url_tags") and creative.url_tags:
        payload["url_tags"] = creative.url_tags.strip()

    return payload
