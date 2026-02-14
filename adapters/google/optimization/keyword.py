from datetime import date
from typing import Optional

from structlog import get_logger
from core.infrastructure.context import auth_context
from adapters.google.client import google_ads_client
from adapters.google.optimization._metrics import build_metrics
from utils.google_dateutils import format_date_range

logger = get_logger(__name__)


class GoogleKeywordAdapter:
    DEFAULT_DURATION = "LAST_30_DAYS"

    def __init__(self):
        self.client = google_ads_client

    async def fetch_keyword_metrics(
        self, account_id: str, parent_account_id: str
    ) -> list:
        """Fetch keyword performance metrics for a Google Ads account."""
        query = _build_keyword_query(
            duration=self.DEFAULT_DURATION, include_metrics=True
        )
        results = await self.client.search_stream(
            query=query,
            customer_id=account_id,
            login_customer_id=parent_account_id,
            client_code=auth_context.client_code,
        )
        keywords = [_transform_row(row) for row in results]
        logger.info(
            "keyword_metrics_fetched", account_id=account_id, count=len(keywords)
        )
        return keywords


def _build_keyword_query(
    campaign_id: Optional[str] = None,
    ad_group_id: Optional[str] = None,
    duration: Optional[str] = None,
    include_negatives: bool = False,
    include_metrics: bool = False,
) -> str:
    date_clause = format_date_range(duration) if duration else ""
    campaign_filter = f"AND campaign.id = {campaign_id}" if campaign_id else ""
    ad_group_filter = f"AND ad_group.id = {ad_group_id}" if ad_group_id else ""
    negative_filter = (
        "" if include_negatives else "AND ad_group_criterion.negative = FALSE"
    )

    metrics_fields = ""
    if include_metrics:
        metrics_fields = """,
               metrics.impressions, metrics.clicks, metrics.conversions,
               metrics.cost_micros, metrics.ctr, metrics.average_cpc,
               metrics.cost_per_conversion"""

    return f"""
        SELECT campaign.id, campaign.name, campaign.advertising_channel_type,
               ad_group.id, ad_group.name,
               ad_group_criterion.criterion_id,
               ad_group_criterion.resource_name,
               ad_group_criterion.status,
               ad_group_criterion.keyword.text,
               ad_group_criterion.keyword.match_type,
               ad_group_criterion.quality_info.quality_score{metrics_fields}
        FROM keyword_view
        WHERE campaign.status = 'ENABLED'
            AND campaign.end_date >= '{date.today().strftime("%Y-%m-%d")}'
            AND ad_group.status = 'ENABLED'
            AND ad_group_criterion.status = 'ENABLED'
            {campaign_filter}
            {ad_group_filter}
            {"AND " + date_clause if date_clause else ""}
            {negative_filter}
        ORDER BY ad_group.id, ad_group_criterion.criterion_id
    """.strip()


# TODO: Replace with pydantic model when adapter models are finalized
def _transform_row(row: dict) -> dict:
    campaign = row.get("campaign", {})
    ad_group = row.get("adGroup", {})
    criterion = row.get("adGroupCriterion", {})
    keyword_info = criterion.get("keyword", {})

    return {
        "keyword": keyword_info.get("text", "").strip().lower(),
        "criterion_id": str(criterion.get("criterionId", "")),
        "resource_name": criterion.get("resourceName", ""),
        "match_type": keyword_info.get("matchType", "PHRASE"),
        "ad_group_id": str(ad_group.get("id", "")),
        "ad_group_name": ad_group.get("name", ""),
        "campaign_id": str(campaign.get("id", "")),
        "campaign_name": campaign.get("name", ""),
        "status": criterion.get("status", "UNKNOWN"),
        "is_negative": criterion.get("negative", False),
        "quality_score": criterion.get("qualityInfo", {}).get("qualityScore"),
        "metrics": build_metrics(row.get("metrics", {})),
    }
