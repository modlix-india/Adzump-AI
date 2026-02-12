from structlog import get_logger
from core.infrastructure.context import auth_context
from adapters.google.client import GoogleAdsClient
from utils.google_dateutils import format_duration_clause
from adapters.google.optimization._metrics import build_metrics
from datetime import date

logger = get_logger(__name__)


class GoogleGenderAdapter:
    DEFAULT_DURATION = "LAST_30_DAYS"

    def __init__(self):
        self.client = GoogleAdsClient()

    async def fetch_gender_metrics(
        self,
        account_id: str,
        parent_account_id: str,
    ) -> list:
        duration_clause = format_duration_clause(self.DEFAULT_DURATION)
        today = date.today().strftime("%Y-%m-%d")

        # Performance Metrics (gender_view)
        performance_query = f"""
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
        WHERE segments.date {duration_clause}
          AND campaign.status = 'ENABLED'
          AND ad_group.status = 'ENABLED'
          AND campaign.end_date >= '{today}'
        """

        # Current Targeting State
        targeting_query = """
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

        try:
            performance_results = await self.client.search_stream(
                query=performance_query,
                customer_id=account_id,
                login_customer_id=parent_account_id,
                client_code=auth_context.client_code,
            )

            targeting_results = await self.client.search_stream(
                query=targeting_query,
                customer_id=account_id,
                login_customer_id=parent_account_id,
                client_code=auth_context.client_code,
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

    # Merge performance + targeting state
    def _merge_metrics_with_targeting(
        self,
        performance_results: list,
        targeting_results: list,
    ) -> list:
        targeting_map = {}

        for entry in targeting_results:
            ad_group_id = str(entry.get("adGroup", {}).get("id"))
            gender_type = (
                entry.get("adGroupCriterion", {}).get("gender", {}).get("type")
            )

            targeting_map.setdefault(ad_group_id, set()).add(gender_type)

        merged = []

        for entry in performance_results:
            ad_group_id = str(entry.get("adGroup", {}).get("id"))
            metrics_data = build_metrics(entry.get("metrics", {}))

            entry["calculated_metrics"] = metrics_data

            entry["targeted_genders"] = list(targeting_map.get(ad_group_id, []))

            merged.append(entry)

        return merged
