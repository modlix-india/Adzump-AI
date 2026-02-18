from datetime import date

from structlog import get_logger
from core.infrastructure.context import auth_context
from adapters.google.client import google_ads_client
from utils.helpers import micros_to_rupees
from utils.google_dateutils import format_date_range

logger = get_logger(__name__)

# All possible Google Ads age ranges
ALL_AGE_RANGES = [
    "AGE_RANGE_18_24",
    "AGE_RANGE_25_34",
    "AGE_RANGE_35_44",
    "AGE_RANGE_45_54",
    "AGE_RANGE_55_64",
    "AGE_RANGE_65_UP",
]


class GoogleAgeAdapter:
    DEFAULT_DURATION = "LAST_30_DAYS"

    def __init__(self):
        self.client = google_ads_client

    async def fetch_age_metrics(self, account_id: str, parent_account_id: str) -> list:
        """Fetch age metrics for a Google Ads account with calculated performance metrics."""
        duration_clause = format_date_range(self.DEFAULT_DURATION)

        query = f"""
        SELECT campaign.id, campaign.name, campaign.advertising_channel_type,
               ad_group.id, ad_group.name,
               ad_group_criterion.resource_name,
               ad_group_criterion.age_range.type,
               ad_group_criterion.status,
               metrics.impressions, metrics.clicks, metrics.conversions, metrics.cost_micros
        FROM age_range_view
        WHERE {duration_clause}
          AND campaign.status = 'ENABLED'
          AND campaign.end_date >= '{date.today().strftime("%Y-%m-%d")}'
          AND ad_group.status = 'ENABLED'
          AND ad_group_criterion.status != 'REMOVED'
        """

        try:
            results = await self.client.search_stream(
                query=query,
                customer_id=account_id,
                login_customer_id=parent_account_id,
                client_code=auth_context.client_code,
            )
            return self._calculate_metrics(results)
        except Exception as e:
            logger.warning(
                "Failed to fetch Google Ads age metrics",
                account_id=account_id,
                error=str(e),
            )
            return []

    async def fetch_age_targeting(
        self, account_id: str, parent_account_id: str, campaign_ids: list[str]
    ) -> dict[str, set[str]]:
        if not campaign_ids:
            return {}

        # Format campaign IDs for query
        campaign_ids_str = ", ".join(campaign_ids)

        query = f"""
        SELECT ad_group.id, ad_group.name,
               ad_group_criterion.age_range.type,
               ad_group_criterion.status
        FROM ad_group_criterion
        WHERE campaign.id IN ({campaign_ids_str})
          AND ad_group_criterion.type = 'AGE_RANGE'
          AND ad_group_criterion.status IN ('ENABLED', 'PAUSED')
          AND campaign.status = 'ENABLED'
          AND ad_group.status = 'ENABLED'
        """

        try:
            results = await self.client.search_stream(
                query=query,
                customer_id=account_id,
                login_customer_id=parent_account_id,
                client_code=auth_context.client_code,
            )
            return self._build_targeting_map(results)
        except Exception as e:
            logger.warning(
                "Failed to fetch age targeting state",
                account_id=account_id,
                error=str(e),
            )
            return {}

    def _build_targeting_map(self, results: list) -> dict[str, set[str]]:
        """Build ad_group_id → set of targeted age ranges mapping."""
        targeting_map = {}
        for entry in results:
            ad_group = entry.get("adGroup", {})
            criterion = entry.get("adGroupCriterion", {})

            ad_group_id = str(ad_group.get("id", ""))
            age_range = criterion.get("ageRange", {}).get("type", "")
            status = criterion.get("status", "")

            # Only include ENABLED age ranges that are in our usable list
            # Exclude AGE_RANGE_UNDETERMINED as it's not actionable
            if (
                ad_group_id
                and age_range
                and status == "ENABLED"
                and age_range in ALL_AGE_RANGES
            ):
                if ad_group_id not in targeting_map:
                    targeting_map[ad_group_id] = set()
                targeting_map[ad_group_id].add(age_range)

        return targeting_map

    def _calculate_metrics(self, results: list) -> list:
        """Calculate performance metrics (CTR, CPA, CPC) from raw Google Ads data."""
        calculated = []
        for entry in results:
            metrics = entry.get("metrics", {})
            cost_micros = float(metrics.get("costMicros", 0))
            clicks = float(metrics.get("clicks", 0))
            impressions = float(metrics.get("impressions", 0))
            conversions = float(metrics.get("conversions", 0))

            cost = micros_to_rupees(cost_micros)

            entry["calculated_metrics"] = {
                "cost": round(cost, 2),
                "CPA": round(cost / conversions, 2) if conversions > 0 else 0.0,
                "CTR": round((clicks / impressions * 100), 2)
                if impressions > 0
                else 0.0,
                "CPC": round(cost / clicks, 2) if clicks > 0 else 0.0,
            }
            calculated.append(entry)

        return calculated
