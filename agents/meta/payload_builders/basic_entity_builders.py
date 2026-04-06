from agents.meta.utils.payload_helpers import build_name
from core.models.meta import AdCreationStage, CampaignPayload, AdPayload


def build_campaign_payload(campaign: CampaignPayload) -> dict:
    campaign = campaign.model_dump(mode="json", exclude_none=True)
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


def build_ad_payload(ad: AdPayload) -> dict:
    ad = ad.model_dump(mode="json", exclude_none=True)
    return {
        "name": build_name(ad["name"], AdCreationStage.AD),
        "creative": {},
        "status": ad.get("status"),
    }
