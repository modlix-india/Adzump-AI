from datetime import date

from structlog import get_logger
from core.infrastructure.context import auth_context
from adapters.google.client import GoogleAdsClient
from utils.google_dateutils import format_date_range
from adapters.google.optimization._metrics import build_metrics

logger = get_logger(__name__)


class GoogleSearchTermAdapter:
    DEFAULT_DURATION = "LAST_30_DAYS"

    def __init__(self):
        self.client = GoogleAdsClient()

    async def fetch_search_terms(
        self, account_id: str, parent_account_id: str
    ) -> list:
        """
        Returns: [{"campaign_id", "campaign_name", "campaign_type", "ad_group_id",
            "ad_group_name", "search_term", "status", "match_type",
            "metrics": {"impressions", "clicks", "conversions", "cost",
                "ctr", "average_cpc", "cost_per_conversion"}}]
        """
        duration_clause = format_date_range(self.DEFAULT_DURATION)

        query = f"""
        SELECT
            campaign.id,
            campaign.name,
            campaign.advertising_channel_type,
            ad_group.id,
            ad_group.name,
            search_term_view.search_term,
            search_term_view.status,
            segments.search_term_match_type,
            metrics.impressions,
            metrics.clicks,
            metrics.ctr,
            metrics.average_cpc,
            metrics.cost_micros,
            metrics.conversions,
            metrics.cost_per_conversion
        FROM search_term_view
        WHERE
            {duration_clause}
            AND search_term_view.status IN ('NONE')
            AND ad_group.status = 'ENABLED'
            AND campaign.status = 'ENABLED'
            AND campaign.end_date >= '{date.today().strftime("%Y-%m-%d")}'
        """

        try:
            results = await self.client.search_stream(
                query=query,
                customer_id=account_id,
                login_customer_id=parent_account_id,
                client_code=auth_context.client_code,
            )
            return self._transform_results(results)
        except Exception as e:
            logger.warning(
                "Failed to fetch search terms",
                account_id=account_id,
                error=str(e),
            )
            return []

    # TODO: Replace with pydantic model when adapter models are finalized
    def _transform_results(self, results: list) -> list:
        """Transform raw API results into structured search term data."""
        transformed = []
        for entry in results:
            campaign = entry.get("campaign", {})
            ad_group = entry.get("adGroup", {})
            search_term_view = entry.get("searchTermView", {})

            search_term = search_term_view.get("searchTerm")
            if not search_term:
                continue

            transformed.append({
                "campaign_id": str(campaign.get("id")),
                "campaign_name": campaign.get("name"),
                "campaign_type": campaign.get("advertisingChannelType"),
                "ad_group_id": str(ad_group.get("id")),
                "ad_group_name": ad_group.get("name"),
                "search_term": search_term,
                "status": search_term_view.get("status"),
                "match_type": entry.get("segments", {}).get("searchTermMatchType"),
                "metrics": build_metrics(entry.get("metrics", {})),
            })

        return transformed

