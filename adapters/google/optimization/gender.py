import asyncio
from datetime import date

from structlog import get_logger
from core.infrastructure.context import auth_context
from adapters.google.client import google_ads_client
from utils.google_dateutils import format_date_range
from adapters.google.optimization._metrics import build_metrics

logger = get_logger(__name__)


class GoogleGenderAdapter:
    DEFAULT_DURATION = "LAST_30_DAYS"

    PERFORMANCE_QUERY = """
        SELECT
            campaign.id,
            campaign.name,
            campaign.advertising_channel_type,
            campaign.end_date,
            ad_group.id,
            ad_group.name,
            ad_group_criterion.gender.type,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.cost_micros
        FROM gender_view
        WHERE {duration_clause}
          AND campaign.status = 'ENABLED'
          AND ad_group.status = 'ENABLED'
          AND campaign.end_date >= '{today}'
    """

    TARGETING_QUERY = """
        SELECT
            campaign.id,
            ad_group.id,
            ad_group_criterion.resource_name,
            ad_group_criterion.gender.type
        FROM ad_group_criterion
        WHERE ad_group_criterion.type = GENDER
          AND campaign.status = 'ENABLED'
          AND ad_group.status = 'ENABLED'
    """

    def __init__(self):
        self.client = google_ads_client

    async def fetch_gender_metrics(
        self,
        account_id: str,
        parent_account_id: str,
    ) -> list[dict]:
        duration_clause = format_date_range(self.DEFAULT_DURATION)
        today = date.today().isoformat()

        try:
            performance_results, targeting_results = await asyncio.gather(
                self.client.search_stream(
                    query=self.PERFORMANCE_QUERY.format(
                        duration_clause=duration_clause, today=today
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

            return self._merge_metrics_with_targeting(
                performance_results,
                targeting_results,
            )

        except Exception as e:
            logger.warning(
                "Failed to fetch Google Ads gender metrics",
                account_id=account_id,
                error=str(e),
            )
            return []

    def _merge_metrics_with_targeting(
        self,
        performance_results: list[dict],
        targeting_results: list[dict],
    ) -> list[dict]:
        """Transform raw Google Ads data into clean domain dicts.

        Each entry is one gender's performance in one ad group:
            - campaign_id, campaign_name, campaign_type
            - ad_group_id, ad_group_name
            - gender_type: "MALE" | "FEMALE" | "UNDETERMINED"
            - metrics: {impressions, clicks, conversions, cost, ctr, average_cpc, cpl, conv_rate}
            - is_targeted: whether this gender is currently targeted
            - resource_name: criterion resource_name (None if not targeted)
            - targeted_genders: all genders targeted in this ad group
        """
        targeting_map: dict[str, list[dict]] = {}

        for entry in targeting_results:
            ad_group_id = str(entry.get("adGroup", {}).get("id"))
            criterion = entry.get("adGroupCriterion", {})

            targeting_map.setdefault(ad_group_id, []).append(
                {
                    "gender": criterion.get("gender", {}).get("type"),
                    "resource_name": criterion.get("resourceName"),
                }
            )

        merged = []

        for entry in performance_results:
            campaign = entry.get("campaign", {})
            ad_group = entry.get("adGroup", {})
            ad_group_id = str(ad_group.get("id"))
            gender_type = (
                entry.get("adGroupCriterion", {}).get("gender", {}).get("type")
            )

            criteria = targeting_map.get(ad_group_id, [])
            matching = next((c for c in criteria if c["gender"] == gender_type), None)

            merged.append(
                {
                    "campaign_id": str(campaign.get("id")),
                    "campaign_name": campaign.get("name"),
                    "campaign_type": campaign.get("advertisingChannelType"),
                    "ad_group_id": ad_group_id,
                    "ad_group_name": ad_group.get("name"),
                    "gender_type": gender_type,
                    "metrics": build_metrics(entry.get("metrics", {})),
                    "is_targeted": matching is not None,
                    "resource_name": matching["resource_name"] if matching else None,
                    "targeted_genders": [c["gender"] for c in criteria],
                }
            )

        return merged
