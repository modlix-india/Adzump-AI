from agents.meta.utils.payload_helpers import build_name
from core.models.meta import AdCreationStage


def build_campaign_payload(campaign: dict) -> dict:
    payload = {
        "name": build_name(campaign.get("name"), AdCreationStage.CAMPAIGN),
        "objective": campaign.get("objective"),
        "status": campaign.get("status"),
    }

    if campaign.get("special_ad_categories"):
        payload["special_ad_categories"] = campaign.get("special_ad_categories")

    if campaign.get("special_ad_category_country"):
        payload["special_ad_category_country"] = campaign.get(
            "special_ad_category_country"
        )

    return payload
