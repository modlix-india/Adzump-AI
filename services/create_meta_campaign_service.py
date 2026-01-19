from services.meta_ad_assets_service import MetaAdAssetsService
from third_party.meta.services.build_meta_campaign_payload import build_meta_campaign_payload


async def create_meta_campaign(
    business_name: str,
    website_url: str,
    budget: float,
    duration_days: int,
    goal: str
):
    ad_assets = await MetaAdAssetsService.generate_ad_assets(
        business_name=business_name,
        website_url=website_url,
        goal=goal
    )

    payload = build_meta_campaign_payload(
        business_name=business_name,
        budget=budget,
        duration_days=duration_days,
        ad_copy=ad_assets
    )

    return {
        "platform": "meta",
        "payload": payload
    }