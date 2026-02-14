from datetime import date

from structlog import get_logger
from core.infrastructure.context import auth_context
from adapters.google.client import google_ads_client
from adapters.google.optimization._metrics import build_metrics

logger = get_logger(__name__)


class GoogleLocationAdapter:
    DEFAULT_DURATION = "LAST_30_DAYS"

    def __init__(self):
        self.client = google_ads_client

    async def fetch_campaign_location_targets(
        self, account_id: str, parent_account_id: str
    ) -> dict[str, dict]:
        today = date.today().isoformat()
        query = f"""
        SELECT campaign.id, campaign.name, campaign.advertising_channel_type,
               campaign_criterion.resource_name,
               campaign_criterion.location.geo_target_constant
        FROM campaign_criterion
        WHERE campaign.status = 'ENABLED'
          AND campaign.end_date >= '{today}'
          AND campaign_criterion.type = LOCATION
          AND campaign_criterion.negative = FALSE
        """

        results = await self.client.search_stream(
            query=query,
            customer_id=account_id,
            login_customer_id=parent_account_id,
            client_code=auth_context.client_code,
        )
        return self._group_location_targets(results)

    async def fetch_location_performance(
        self, account_id: str, parent_account_id: str
    ) -> dict[str, dict]:
        query = f"""
        SELECT campaign.id, campaign.name, campaign.advertising_channel_type,
               location_view.resource_name,
               campaign_criterion.location.geo_target_constant,
               metrics.impressions, metrics.clicks, metrics.conversions,
               metrics.conversions_value, metrics.cost_micros
        FROM location_view
        WHERE campaign.status = 'ENABLED'
          AND campaign.end_date >= '{date.today().isoformat()}'
          AND metrics.impressions > 0
          AND segments.date DURING {self.DEFAULT_DURATION}
        """

        results = await self.client.search_stream(
            query=query,
            customer_id=account_id,
            login_customer_id=parent_account_id,
            client_code=auth_context.client_code,
        )
        return self._group_location_performance(results)

    async def fetch_geo_target_details(
        self, account_id: str, parent_account_id: str, geo_constants: list[str]
    ) -> dict[str, dict]:
        if not geo_constants:
            return {}

        geo_list = ", ".join(f"'{g}'" for g in geo_constants)
        query = f"""
        SELECT geo_target_constant.resource_name,
               geo_target_constant.name,
               geo_target_constant.country_code,
               geo_target_constant.target_type
        FROM geo_target_constant
        WHERE geo_target_constant.resource_name IN ({geo_list})
        """

        results = await self.client.search_stream(
            query=query,
            customer_id=account_id,
            login_customer_id=parent_account_id,
            client_code=auth_context.client_code,
        )
        return {
            row["geoTargetConstant"]["resourceName"]: {
                "geo_target_constant": row["geoTargetConstant"]["resourceName"],
                "location_name": row["geoTargetConstant"]["name"],
                "country_code": row["geoTargetConstant"]["countryCode"],
                "location_type": row["geoTargetConstant"]["targetType"],
            }
            for row in results
        }

    def _group_location_targets(self, results: list) -> dict[str, dict]:
        campaigns: dict[str, dict] = {}
        for row in results:
            campaign = row.get("campaign", {})
            campaign_id = str(campaign.get("id"))

            campaigns.setdefault(
                campaign_id,
                {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign.get("name"),
                    "campaign_type": campaign.get("advertisingChannelType"),
                    "targeted_locations": {},
                },
            )

            criterion = row.get("campaignCriterion", {})
            geo_constant = criterion.get("location", {}).get("geoTargetConstant")
            criterion_resource_name = criterion.get("resourceName")
            if geo_constant:
                campaigns[campaign_id]["targeted_locations"][geo_constant] = (
                    criterion_resource_name
                )

        return campaigns

    def _group_location_performance(self, results: list) -> dict[str, dict]:
        campaign_metrics: dict[str, dict] = {}
        for row in results:
            geo_constant = self._extract_geo_constant(row)
            if not geo_constant:
                continue

            campaign_id = str(row["campaign"]["id"])
            metrics = build_metrics(row.get("metrics", {}))
            metrics["cost_micros"] = int(row.get("metrics", {}).get("costMicros", 0))
            metrics["conversions_value"] = float(
                row.get("metrics", {}).get("conversionsValue", 0)
            )

            campaign_metrics.setdefault(campaign_id, {})[geo_constant] = metrics

        return campaign_metrics

    def _extract_geo_constant(self, row: dict) -> str | None:
        criterion = row.get("campaignCriterion")
        if criterion:
            location = criterion.get("location")
            if location and location.get("geoTargetConstant"):
                return location["geoTargetConstant"]

        resource_name = row.get("locationView", {}).get("resourceName")
        if resource_name and "~" in resource_name:
            geo_id = resource_name.rsplit("~", 1)[-1]
            return f"geoTargetConstants/{geo_id}"

        return None
