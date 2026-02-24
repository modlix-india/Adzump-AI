import asyncio
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

    PERFORMANCE_QUERY = """
        SELECT campaign.id, campaign.name, campaign.advertising_channel_type,
               ad_group.id, ad_group.name,
               ad_group_criterion.age_range.type,
               ad_group_criterion.resource_name,
               ad_group_criterion.status,
               metrics.impressions, metrics.clicks, metrics.conversions, metrics.cost_micros
        FROM age_range_view
        WHERE {duration_clause}
          AND campaign.status = 'ENABLED'
          AND campaign.end_date >= '{today}'
          AND ad_group.status = 'ENABLED'
          AND ad_group_criterion.status != 'REMOVED'
    """

    TARGETING_QUERY = """
        SELECT
            ad_group.id,
            ad_group_criterion.age_range.type,
            ad_group_criterion.status
        FROM ad_group_criterion
        WHERE ad_group_criterion.type = 'AGE_RANGE'
          AND ad_group_criterion.status IN ('ENABLED', 'PAUSED')
          AND campaign.status = 'ENABLED'
          AND ad_group.status = 'ENABLED'
    """

    def __init__(self):
        self.client = google_ads_client

    async def fetch_age_metrics(
        self, account_id: str, parent_account_id: str
    ) -> list[dict]:
        duration_clause = format_date_range(self.DEFAULT_DURATION)
        today = date.today().isoformat()

        try:
            performance_results, targeting_results = await asyncio.gather(
                self.client.search_stream(
                    query=self.PERFORMANCE_QUERY.format(
                        duration_clause=duration_clause,
                        today=today,
                    ),
                    customer_id=account_id,
                    login_customer_id=parent_account_id,
                    client_code=auth_context.client_code,
                ),
                self.client.search_stream(
                    query=self.TARGETING_QUERY,
                    customer_id=account_id,
                    login_customer_id=parent_account_id,
                    client_code=auth_context.client_code,
                ),
            )

            targeting_map = self._build_targeting_map(targeting_results)
            return self._merge_metrics_with_targeting(
                performance_results, targeting_map
            )

        except Exception as e:
            logger.warning(
                "Failed to fetch Google Ads age metrics",
                account_id=account_id,
                error=str(e),
            )
            return []

    def _build_targeting_map(self, results: list) -> dict[str, set[str]]:
        """Build ad_group_id → set of ENABLED targeted age ranges."""
        targeting_map: dict[str, set[str]] = {}
        for entry in results:
            ad_group = entry.get("adGroup", {})
            criterion = entry.get("adGroupCriterion", {})

            ad_group_id = str(ad_group.get("id", ""))
            age_range = criterion.get("ageRange", {}).get("type", "")
            status = criterion.get("status", "")

            if (
                ad_group_id
                and age_range
                and status == "ENABLED"
                and age_range in ALL_AGE_RANGES
            ):
                targeting_map.setdefault(ad_group_id, set()).add(age_range)

        return targeting_map

    def _merge_metrics_with_targeting(
        self,
        performance_results: list,
        targeting_map: dict[str, set[str]],
    ) -> list[dict]:
        seen: dict[tuple, dict] = {}
        ad_group_meta: dict[str, dict] = {}

        for entry in performance_results:
            campaign = entry.get("campaign", {})
            ad_group = entry.get("adGroup", {})
            criterion = entry.get("adGroupCriterion", {})

            ad_group_id = str(ad_group.get("id", ""))
            age_range = criterion.get("ageRange", {}).get("type", "")

            if not ad_group_id or not age_range:
                continue

            ad_group_meta[ad_group_id] = {
                "campaign_id": str(campaign.get("id", "")),
                "campaign_name": campaign.get("name", ""),
                "campaign_type": campaign.get("advertisingChannelType", ""),
                "ad_group_name": ad_group.get("name", ""),
            }

            metrics_raw = entry.get("metrics", {})
            cost_micros = float(metrics_raw.get("costMicros", 0))
            clicks = float(metrics_raw.get("clicks", 0))
            impressions = float(metrics_raw.get("impressions", 0))
            conversions = float(metrics_raw.get("conversions", 0))
            cost = micros_to_rupees(cost_micros)

            is_targeted = age_range in targeting_map.get(ad_group_id, set())

            seen[(ad_group_id, age_range)] = {
                **ad_group_meta[ad_group_id],
                "ad_group_id": ad_group_id,
                "age_range": age_range,
                "is_targeted": is_targeted,
                "resource_name": criterion.get("resourceName"),
                "calculated_metrics": {
                    "cost": round(cost, 2),
                    "CTR": round(clicks / impressions * 100, 2)
                    if impressions > 0
                    else 0.0,
                    "CPA": round(cost / conversions, 2) if conversions > 0 else 0.0,
                    "CPC": round(cost / clicks, 2) if clicks > 0 else 0.0,
                },
            }

        # Inject synthetic rows for age ranges not in age_range_view
        for ad_group_id, meta in ad_group_meta.items():
            for age_range in ALL_AGE_RANGES:
                if (ad_group_id, age_range) not in seen:
                    seen[(ad_group_id, age_range)] = {
                        **meta,
                        "ad_group_id": ad_group_id,
                        "age_range": age_range,
                        "is_targeted": age_range
                        in targeting_map.get(ad_group_id, set()),
                        "resource_name": None,
                        "calculated_metrics": {
                            "cost": 0,
                            "CTR": 0.0,
                            "CPA": 0.0,
                            "CPC": 0.0,
                        },
                    }

        return list(seen.values())
