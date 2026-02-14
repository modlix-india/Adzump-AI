from structlog import get_logger
from adapters.google.client import GoogleAdsClient

logger = get_logger(__name__)


class GoogleAssetsAdapter:
    """Adapter for fetching asset and campaign data from Google Ads API."""

    def __init__(self):
        self.client = GoogleAdsClient()

    async def fetch_all_campaigns(
        self, customer_id: str, login_customer_id: str, client_code: str
    ) -> list[dict]:
        """Fetch all enabled search campaigns for a customer account."""
        query = """
            SELECT 
                campaign.id,
                campaign.name,
                campaign.status,
                campaign.advertising_channel_type
            FROM campaign
            WHERE campaign.status = 'ENABLED'
              AND campaign.advertising_channel_type = 'SEARCH'
        """

        try:
            results = await self.client.search_stream(
                query=query,
                customer_id=customer_id,
                login_customer_id=login_customer_id,
                client_code=client_code,
            )

            campaigns = []
            for result in results:
                campaign_data = result.get("campaign", {})
                campaigns.append(
                    {
                        "id": str(campaign_data.get("id", "")),
                        "name": campaign_data.get("name", ""),
                        "status": campaign_data.get("status", ""),
                        "channel": campaign_data.get(
                            "advertisingChannelType", "UNKNOWN"
                        ),
                    }
                )

            logger.info(
                "Fetched campaigns",
                customer_id=customer_id,
                count=len(campaigns),
            )
            return campaigns

        except Exception as e:
            logger.error(
                "Failed to fetch campaigns",
                customer_id=customer_id,
                error=str(e),
            )
            raise

    async def fetch_asset_performance(
        self,
        customer_id: str,
        login_customer_id: str,
        client_code: str,
        campaign_id: str | None = None,
    ) -> list[dict]:
        campaign_filter = f"AND campaign.id = {campaign_id}" if campaign_id else ""

        query = f"""
            SELECT 
                campaign.id, campaign.name,
                campaign.advertising_channel_type,
                ad_group.id, ad_group.name,
                ad_group_ad.ad.id,
                ad_group_ad.ad.name,
                ad_group_ad_asset_view.resource_name,
                ad_group_ad_asset_view.asset,
                ad_group_ad_asset_view.field_type,
                ad_group_ad_asset_view.performance_label,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros
            FROM ad_group_ad_asset_view
            WHERE ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'
              AND segments.date DURING LAST_30_DAYS
              {campaign_filter}
              AND ad_group_ad_asset_view.field_type IN ('HEADLINE', 'DESCRIPTION')
        """

        try:
            results = await self.client.search_stream(
                query=query,
                customer_id=customer_id,
                login_customer_id=login_customer_id,
                client_code=client_code,
            )

            scope = f"campaign {campaign_id}" if campaign_id else "account"
            logger.info(
                f"Fetched asset performance data for {scope}",
                customer_id=customer_id,
                campaign_id=campaign_id,
                results_count=len(results),
            )
            return results

        except Exception as e:
            logger.error(
                "Failed to fetch asset performance",
                customer_id=customer_id,
                campaign_id=campaign_id,
                error=str(e),
            )
            raise

    async def fetch_asset_text(
        self,
        asset_ids: list[str],
        customer_id: str,
        login_customer_id: str,
        client_code: str,
    ) -> dict[str, str]:
        """Fetch text content for a list of asset IDs."""
        if not asset_ids:
            return {}

        # Filter out empty IDs
        valid_ids = [aid for aid in asset_ids if aid]
        if not valid_ids:
            return {}

        ids_str = ", ".join(valid_ids)
        query = f"""
            SELECT asset.id, asset.name, asset.text_asset.text, asset.type
            FROM asset
            WHERE asset.id IN ({ids_str})
        """

        try:
            results = await self.client.search_stream(
                query=query,
                customer_id=customer_id,
                login_customer_id=login_customer_id,
                client_code=client_code,
            )

            # Convert to dict: asset_id -> text
            asset_map = {}
            for result in results:
                asset = result.get("asset", {})
                asset_id = asset.get("id")
                text = asset.get("textAsset", {}).get("text", "")
                if asset_id and text:
                    asset_map[str(asset_id)] = text

            logger.info(
                "Fetched asset text",
                customer_id=customer_id,
                requested_count=len(valid_ids),
                retrieved_count=len(asset_map),
            )
            return asset_map

        except Exception as e:
            logger.error(
                "Failed to fetch asset text",
                customer_id=customer_id,
                error=str(e),
            )
            return {}
