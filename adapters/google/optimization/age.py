from structlog import get_logger
from core.infrastructure.context import auth_context
from adapters.google.client import GoogleAdsClient
from utils.helpers import micros_to_rupees
from utils.google_dateutils import format_date_range

logger = get_logger(__name__)


class GoogleAgeAdapter:
    DEFAULT_DURATION = "LAST_30_DAYS"

    def __init__(self):
        self.client = GoogleAdsClient()

    async def fetch_age_metrics(self, account_id: str, parent_account_id: str) -> list:
        """Fetch age metrics for a Google Ads account with calculated performance metrics."""
        duration_clause = format_date_range(self.DEFAULT_DURATION)

        query = f"""
        SELECT campaign.id, campaign.name, campaign.advertising_channel_type,
               ad_group.id, ad_group.name,
               ad_group_criterion.age_range.type,
               metrics.impressions, metrics.clicks, metrics.conversions, metrics.cost_micros
        FROM age_range_view
        WHERE {duration_clause}
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
            return self._calculate_metrics(results)
        except Exception as e:
            logger.warning(
                "Failed to fetch Google Ads age metrics",
                account_id=account_id,
                error=str(e),
            )
            return []

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
