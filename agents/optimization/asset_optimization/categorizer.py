import structlog

logger = structlog.get_logger(__name__)


class AssetCategorizer:
    """Categorizes assets into performance tiers (LOW, GOOD/BEST, LEARNING/PENDING, OTHER)."""

    def categorize_assets(self, performance_data: list, asset_details: dict) -> dict:
        low_assets = []
        tier_1 = []  # GOOD/BEST
        tier_2 = []  # LEARNING/PENDING
        tier_3 = []  # Other

        for item in performance_data:
            label = item.get("adGroupAdAssetView", {}).get("performanceLabel")

            asset_resource = item.get("adGroupAdAssetView", {}).get("asset", "")
            asset_id = asset_resource.split("/")[-1]

            asset_type = item.get("adGroupAdAssetView", {}).get("fieldType")
            impressions = int(item.get("metrics", {}).get("impressions", 0))

            # Extract ad ID - API returns id directly
            ad_data = item.get("adGroupAd", {}).get("ad", {})
            ad_id = ad_data.get("id", "") if isinstance(ad_data, dict) else ""
            ad_name = ad_data.get("name", "") if isinstance(ad_data, dict) else ""

            text = asset_details.get(asset_id, "")
            if not text:
                continue  # Skip assets without text

            asset_obj = {
                "asset_id": asset_id,
                "asset_type": asset_type,
                "text": text,
                "impressions": impressions,
                "label": label or "UNKNOWN",
                "ad_group_id": item.get("adGroup", {}).get("id"),
                "ad_group_name": item.get("adGroup", {}).get("name"),
                "campaign_name": item.get("campaign", {}).get("name"),
                "ad_id": ad_id,
                "ad_name": ad_name,
                "resource_name": item.get("adGroupAdAssetView", {}).get(
                    "resourceName", ""
                ),
            }

            # Categorize into tiers
            if label == "LOW":
                low_assets.append(asset_obj)
            elif label in ["GOOD", "BEST"]:
                tier_1.append(asset_obj)
            elif label in ["LEARNING", "PENDING"]:
                tier_2.append(asset_obj)
            else:
                tier_3.append(asset_obj)

        return {
            "low_assets": low_assets,
            "tier_1": tier_1,
            "tier_2": tier_2,
            "tier_3": tier_3,
        }
