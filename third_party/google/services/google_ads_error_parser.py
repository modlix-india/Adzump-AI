# # google_ads_error_parser_enhanced.py

from typing import Dict, Any, List
import logging
import html

# existing maps (extend as needed)
ERROR_MESSAGE_MAP = {
    "TOO_LONG": {"friendly": "Text too long", "severity": "USER_FIX"},
    # ... other mappings ...
}

# optional: maximum chars for known fields (best-effort; Google doesn't always return limits)
# Keep this conservative; if empty, we won't claim a specific max.
KNOWN_FIELD_LIMITS = {
    # "responsive_search_ad.headlines.text": 30,  # example if you want to enforce known limits
}


def build_field_path(field_path_elements: List[Dict[str, Any]]) -> str:
    """
    Convert fieldPathElements into a dot-like path with indexes for lists.
    e.g. [{'fieldName':'responsive_search_ad'},{'fieldName':'headlines','index':0},{'fieldName':'text'}]
    -> "responsive_search_ad.headlines[0].text"
    """
    parts = []
    for el in field_path_elements:
        name = el.get("fieldName")
        if name is None:
            continue
        idx = el.get("index")
        if idx is not None:
            parts.append(f"{name}[{idx}]")
        else:
            parts.append(name)
    return ".".join(parts) if parts else "unknown"


def map_field_to_entity(field_path: str) -> Dict[str, str]:
    """
    Return entity + friendly field name for UI highlighting.
    Extend mapping table as needed.
    """
    # simple heuristics
    if "responsive_search_ad" in field_path:
        if "headlines" in field_path:
            return {"entity": "AD", "field": "headline"}
        if "descriptions" in field_path:
            return {"entity": "AD", "field": "description"}
    if "ad_group_criterion" in field_path or "keywords" in field_path:
        return {"entity": "KEYWORD", "field": "keyword_text"}
    if "campaign" in field_path:
        return {"entity": "CAMPAIGN", "field": field_path}
    # fallback
    return {"entity": "UNKNOWN", "field": field_path}


def sanitize_offending_value(val: str, max_len: int = 200) -> str:
    """
    Avoid returning extremely large or harmful strings to frontend.
    Escape HTML and truncate to max_len characters for display.
    """
    if not isinstance(val, str):
        return str(val)
    escaped = html.escape(val)
    if len(escaped) > max_len:
        return escaped[: max_len - 3] + "..."
    return escaped


def handle_string_length_error(err: Dict[str, Any]) -> Dict[str, Any]:
    """
    Special handling for string length errors: get trigger, compute length and return
    an actionable message.
    """
    trigger = err.get("trigger", {})
    offending = trigger.get("stringValue") or trigger.get("value") or ""
    field_location = err.get("location", {}).get("fieldPathElements", [])
    field_path = build_field_path(field_location)
    mapping = map_field_to_entity(field_path)

    sanitized_value = sanitize_offending_value(offending)
    length = len(offending) if isinstance(offending, str) else None

    # Try to get a known limit (best-effort)
    known_limit = KNOWN_FIELD_LIMITS.get(field_path)

    # Craft message
    if known_limit:
        message = (
            f"{mapping['field'].capitalize()} is too long ({length} chars). "
            f"Max allowed is {known_limit} characters. Please shorten it."
        )
    else:
        message = (
            f"{mapping['field'].capitalize()} is too long ({length} chars). "
            "Please shorten it to meet Google Ads limits."
        )

    return {
        "entity": mapping["entity"],
        "field": mapping["field"],
        "message": message,
        "offending_value": sanitized_value,
        "offending_length": length,
        "hint": "Remove extra words, abbreviate, or use fewer characters."
    }


def parse_google_ads_error(raw_error: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhanced parser that extracts trigger values and precise field paths.
    Returns parsed errors + raw_error.
    """
    try:
        errors = raw_error.get("error", {}).get("details", [])[0].get("errors", [])
    except Exception:
        logging.exception("Malformed Google error object")
        return {"success": False, "type": "UNKNOWN", "raw_error": raw_error}

    parsed: List[Dict[str, Any]] = []
    seen = set()
    overall_type = "UNKNOWN"

    for err in errors:
        code_obj = err.get("errorCode", {})
        code = next(iter(code_obj.values()), None)  # e.g. "TOO_LONG"

        # skip cascade errors if desired
        if code == "RESOURCE_NOT_FOUND":
            continue

        if code in seen:
            continue
        seen.add(code)

        # Specialized handling for string length (TOO_LONG)
        if code in ("TOO_LONG", "STRING_TOO_LONG", "STRING_LENGTH_TOO_LONG", "stringLengthError"):
            parsed.append(handle_string_length_error(err))
            overall_type = "USER_FIX"
            continue

        # Generic mapping for known errors
        if code and code in ERROR_MESSAGE_MAP:
            m = ERROR_MESSAGE_MAP[code]
            parsed.append({
                "entity": m.get("entity", "UNKNOWN"),
                "field": m.get("field", "unknown"),
                "message": m.get("message", err.get("message", "")),
            })
            overall_type = overall_type if overall_type != "UNKNOWN" else "USER_FIX"
            continue

        # Fallback: include location + trigger if present
        field_location = err.get("location", {}).get("fieldPathElements", [])
        field_path = build_field_path(field_location)
        mapping = map_field_to_entity(field_path)
        trigger = err.get("trigger", {})
        offending_value = sanitize_offending_value(trigger.get("stringValue") or trigger.get("value") or "")

        parsed.append({
            "entity": mapping["entity"],
            "field": mapping["field"],
            "message": err.get("message", "Unknown Google Ads error."),
            "offending_value": offending_value
        })
        overall_type = overall_type if overall_type != "UNKNOWN" else "USER_FIX"

    if not parsed:
        parsed.append({
            "entity": "UNKNOWN",
            "field": "UNKNOWN",
            "message": "Dependency failure caused by earlier invalid input."
        })

    return {
        "success": False,
        "type": overall_type,
        "blocking_errors": parsed,
        "raw_error": raw_error
    }

