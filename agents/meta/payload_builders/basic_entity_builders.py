from agents.meta.utils.payload_helpers import build_name
from core.models.meta import AdCreationStage, CampaignPayload, AdPayload


def build_campaign_payload(campaign: CampaignPayload) -> dict:
    """Transform Campaign model into Meta Campaign API payload."""
    payload = {
        "name": build_name(campaign.name, AdCreationStage.CAMPAIGN),
        "objective": campaign.objective.value,
        "status": campaign.status.value,
    }

    if campaign.special_ad_categories:
        payload["special_ad_categories"] = [
            c.value for c in campaign.special_ad_categories
        ]

    if campaign.special_ad_category_country:
        payload["special_ad_category_country"] = list(
            campaign.special_ad_category_country
        )

    return payload


def build_ad_payload(ad: AdPayload) -> dict:
    """Transform Ad model into Meta Ad API payload."""
    return {
        "name": build_name(ad.name, AdCreationStage.AD),
        "status": ad.status.value,
    }
