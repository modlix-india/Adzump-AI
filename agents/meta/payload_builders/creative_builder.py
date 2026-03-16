from urllib.parse import urlparse
from fastapi import HTTPException
from agents.meta.payload_builders.constants import (
    VALID_CREATIVE_TYPES,
    MAX_BODIES,
    MAX_TITLES,
    MAX_IMAGES,
    MAX_DESCRIPTIONS,
    MAX_PRIMARY_TEXT_CHARS,
    MAX_HEADLINE_CHARS,
    MAX_DESCRIPTION_CHARS,
    VALID_CALL_TO_ACTION_TYPES,
    VALID_LEAD_AD_CTA_TYPES,
)



def build_creative_payload(meta_input_payload: dict, is_dynamic: bool) -> dict:
    """
    Routes to the correct builder based on creative type and dynamic flag.
    Supported types: IMAGE | VIDEO (future) | CAROUSEL (future)
    """
    creative         = meta_input_payload["creative"]
    destination_type = meta_input_payload["adset"].get("destination_type")

    if not creative:
        raise HTTPException(status_code=400, detail="Creative payload is required")

    _validate_common_fields(creative, destination_type)

    creative_type = creative.get("type")

    if not creative_type:
        raise HTTPException(
            status_code=400,
            detail=f"creative.type is required. Must be one of: {sorted(VALID_CREATIVE_TYPES)}"
        )

    if creative_type not in VALID_CREATIVE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid creative type '{creative_type}'. Must be one of: {sorted(VALID_CREATIVE_TYPES)}"
        )

    if creative_type == "IMAGE":

        # Meta does not support asset_feed_spec for lead generation destination type
        if is_dynamic and destination_type == "ON_AD":
            raise HTTPException(
                status_code=400,
                detail=(
                    "Dynamic creative (asset_feed_spec) is not supported for ON_AD (Lead Ads). "
                    "Meta requires a single object_story_spec with a lead_gen_form_id. "
                    "Set is_dynamic=false for Lead Ads."
                )
            )
        return (
            _build_dynamic_image_creative(creative, destination_type)
            if is_dynamic
            else _build_non_dynamic_image_creative(creative, destination_type)
        )

    # VIDEO and CAROUSEL — extendable here
    raise HTTPException(
        status_code=400,
        detail=f"Creative type '{creative_type}' is not yet supported"
    )


# COMMON VALIDATOR

def _validate_common_fields(creative: dict, destination_type: str):
    """Validates fields required by all creative types."""

    required_fields = [
        (creative.get("name"),           "creative.name is required"),
        (creative.get("page_id"),        "creative.page_id is required — every Meta ad must be associated with a Facebook Page"),
        (creative.get("call_to_action"), "creative.call_to_action is required"),
    ]

    for value, error_message in required_fields:
        if not value:
            raise HTTPException(status_code=400, detail=error_message)

    call_to_action = creative["call_to_action"]

    if not call_to_action.get("type"):
        raise HTTPException(status_code=400, detail="creative.call_to_action.type is required")

    cta_type = call_to_action["type"]

    # Validate CTA type against all known Meta values
    if cta_type not in VALID_CALL_TO_ACTION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid call_to_action type '{cta_type}'. Must be one of: {sorted(VALID_CALL_TO_ACTION_TYPES)}"
        )

    if destination_type == "ON_AD":
        if cta_type not in VALID_LEAD_AD_CTA_TYPES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid call_to_action type '{cta_type}' for Lead Ads (ON_AD). "
                    f"Must be one of: {sorted(VALID_LEAD_AD_CTA_TYPES)}"
                )
            )

        form_id = call_to_action.get("lead_gen_form_id")
        if not form_id or not str(form_id).strip():
            raise HTTPException(
                status_code=400,
                detail=(
                    "creative.call_to_action.lead_gen_form_id is required and cannot be empty "
                    "for ON_AD (Lead Ads) destination type"
                )
            )

    else:
        url = call_to_action.get("url")
        if not url:
            raise HTTPException(
                status_code=400,
                detail="creative.call_to_action.url is required"
            )
        if not _is_valid_url(url):
            raise HTTPException(
                status_code=400,
                detail="creative.call_to_action.url must be a valid http/https URL"
            )


# URL VALIDATOR

def _is_valid_url(url: str) -> bool:
    """Returns True if the URL has a valid http/https scheme and a netloc."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


# ASSET CONTENT VALIDATOR

def _validate_char_limit(items: list, field_name: str, max_chars: int):
    """Validates character limit for each item in a list."""
    for i, item in enumerate(items):
        if len(item) > max_chars:
            raise HTTPException(
                status_code=400,
                detail=f"{field_name}[{i}] exceeds {max_chars} characters — got {len(item)}"
            )


def _validate_asset_feed_limits(primary_texts, headlines, image_hashes, descriptions):
    """
    Validates Meta asset feed spec:
    - Count limits per field
    - Character limits per item
    """

    # COUNT LIMITS
    count_limits = [
        (primary_texts, "primary_texts", MAX_BODIES),
        (headlines,     "headlines",     MAX_TITLES),
        (image_hashes,  "image_hashes",  MAX_IMAGES),
    ]

    for items, field_name, max_count in count_limits:
        if len(items) > max_count:
            raise HTTPException(
                status_code=400,
                detail=f"{field_name} cannot exceed {max_count} items. Got {len(items)}"
            )

    if descriptions and len(descriptions) > MAX_DESCRIPTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"descriptions cannot exceed {MAX_DESCRIPTIONS} items. Got {len(descriptions)}"
        )

    # CHARACTER LIMITS
    _validate_char_limit(primary_texts, "primary_texts", MAX_PRIMARY_TEXT_CHARS)
    _validate_char_limit(headlines,     "headlines",     MAX_HEADLINE_CHARS)

    if descriptions:
        _validate_char_limit(descriptions, "descriptions", MAX_DESCRIPTION_CHARS)


# ASSET FIELD EXTRACTOR

def _extract_and_validate_assets(creative: dict, context: str) -> tuple:
    """
    Extracts and validates common asset fields used by both
    dynamic and non-dynamic image builders.
    Returns (image_hashes, primary_texts, headlines, descriptions)
    """
    image_hashes  = creative.get("image_hashes")
    primary_texts = creative.get("primary_texts")
    headlines     = creative.get("headlines")
    descriptions  = creative.get("descriptions")

    required_assets = [
        (image_hashes,  "image_hashes"),
        (primary_texts, "primary_texts"),
        (headlines,     "headlines"),
    ]

    for value, field_name in required_assets:
        if not value:
            raise HTTPException(
                status_code=400,
                detail=f"{field_name} required for {context}"
            )

    _validate_asset_feed_limits(primary_texts, headlines, image_hashes, descriptions)

    return image_hashes, primary_texts, headlines, descriptions


# DYNAMIC IMAGE CREATIVE
def _build_dynamic_image_creative(creative: dict, destination_type: str) -> dict:
    """
    Builds Meta asset_feed_spec for dynamic image creative.
    Multiple texts, headlines, images — Meta picks the best combination.
    Only valid for non-ON_AD destination types.
    """
    image_hashes, primary_texts, headlines, descriptions = _extract_and_validate_assets(
        creative, "dynamic image creative"
    )

    call_to_action = creative["call_to_action"]

    asset_feed = {
        "ad_formats":           ["SINGLE_IMAGE"],
        "bodies":               [{"text": text} for text in primary_texts],
        "titles":               [{"text": text} for text in headlines],
        "images":               [{"hash": image_hash} for image_hash in image_hashes],
        "link_urls":            [{"website_url": call_to_action["url"]}],
        "call_to_action_types": [call_to_action["type"]],
    }

    if descriptions:
        asset_feed["descriptions"] = [{"text": desc} for desc in descriptions]

    return {
        "name": creative["name"],
        "object_story_spec": {
            "page_id": creative["page_id"]
        },
        "asset_feed_spec": asset_feed
    }


# NON DYNAMIC IMAGE CREATIVE
def _build_non_dynamic_image_creative(creative: dict, destination_type: str) -> dict:
    """
    Builds Meta object_story_spec for standard single image creative.
    Uses only first text, headline, image — rest are ignored.
    For ON_AD (Lead Ads): uses lead_gen_form_id + required fb.me link.
    For all others: uses website URL.
    """
    image_hashes, primary_texts, headlines, descriptions = _extract_and_validate_assets(
        creative, "image creative"
    )

    call_to_action = creative["call_to_action"]

    link_data = {
        "message":    primary_texts[0],
        "name":       headlines[0],
        "image_hash": image_hashes[0],
    }

    if destination_type == "ON_AD":
        link_data["link"] = "http://fb.me/" # Meta requires "http://fb.me/" as a placeholder for lead ads — the actual destination is the lead_gen_form_id, not a URL
        link_data["call_to_action"] = {
            "type":  call_to_action["type"],
            "value": {"lead_gen_form_id": call_to_action["lead_gen_form_id"]}
        }
    else:
        link_data["link"] = call_to_action["url"]
        link_data["call_to_action"] = {
            "type":  call_to_action["type"],
            "value": {"link": call_to_action["url"]}
        }

    if descriptions:
        link_data["description"] = descriptions[0]

    return {
        "name": creative["name"],
        "object_story_spec": {
            "page_id":   creative["page_id"],
            "link_data": {k: v for k, v in link_data.items() if v is not None}
        }
    }