from typing import List, Dict, Any
import structlog

logger = structlog.get_logger(__name__)


def merge_text_assets(
    current_assets: List[Dict[str, Any]],
    recommendations_to_add: List,
    recommendations_to_remove: List,
) -> List[Dict[str, Any]]:
    """Merge current text assets (headlines/descriptions) with changes."""
    merged_assets = []
    remove_texts = {item.text for item in recommendations_to_remove}

    for asset in current_assets:
        text = asset.get("text")
        if text not in remove_texts:
            merged_assets.append(asset)

    for item in recommendations_to_add:
        # Normalize to camelCase for the Google Ads REST API
        asset_payload = {"text": item.text}

        # Pydantic models might use either naming convention
        pinned = getattr(item, "pinned_field", None) or getattr(
            item, "pinnedField", None
        )
        if pinned:
            asset_payload["pinnedField"] = pinned

        merged_assets.append(asset_payload)

    return merged_assets


def build_rsa_update_operation(
    customer_id: str,
    ad_group_id: str,
    ad_id: str,
    headlines: List[Dict[str, Any]],
    descriptions: List[Dict[str, Any]],
    final_urls: List[str],
    update_mask_fields: List[str],
) -> Dict[str, Any]:
    """Build a single Responsive Search Ad (RSA) update operation."""
    return {
        "adGroupAdOperation": {
            "update": {
                "resourceName": f"customers/{customer_id}/adGroupAds/{ad_group_id}~{ad_id}",
                "ad": {
                    "responsiveSearchAd": {
                        "headlines": headlines,
                        "descriptions": descriptions,
                    },
                    "finalUrls": final_urls,
                },
            },
            "updateMask": ",".join(update_mask_fields),
        }
    }


def populate_sitelink_fields(asset_payload: Dict[str, Any], sitelink: Any) -> None:
    """Populate optional sitelink asset fields (descriptions, URLs, scheduling)."""
    # Ensure sitelinkAsset exists in the payload
    sitelink_asset = asset_payload.setdefault("sitelinkAsset", {})

    if sitelink.description1:
        sitelink_asset["description1"] = sitelink.description1
    if sitelink.description2:
        sitelink_asset["description2"] = sitelink.description2

    if sitelink.final_mobile_url:
        asset_payload["finalMobileUrls"] = [sitelink.final_mobile_url]

    if sitelink.start_date:
        asset_payload["startDateTime"] = sitelink.start_date.isoformat()
    if sitelink.end_date:
        asset_payload["endDateTime"] = sitelink.end_date.isoformat()
