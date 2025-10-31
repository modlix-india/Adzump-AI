from dataclasses import dataclass
from typing import Optional


@dataclass
class Keyword:
    campaign_id: Optional[str]
    campaign_name: Optional[str]
    ad_group_id: Optional[str]
    ad_group_name: Optional[str]
    criterion_id: Optional[str]
    status: Optional[str]
    keyword: Optional[str]
    match_type: Optional[str]
    quality_score: Optional[int]
    impressions: Optional[int]
    clicks: Optional[int]
    ctr: Optional[float]
    average_cpc: Optional[float]
    cost_micros: Optional[int]
    conversions: Optional[float]

    @classmethod
    def from_google_row(cls, row: dict) -> "Keyword":
        """Directly map Google Ads API response row to Keyword."""
        campaign = row.get("campaign", {})
        ad_group = row.get("adGroup", {})
        criterion = row.get("adGroupCriterion", {})
        keyword_info = criterion.get("keyword", {})
        metrics = row.get("metrics", {})

        return cls(
            campaign_id=campaign.get("id"),
            campaign_name=campaign.get("name"),
            ad_group_id=ad_group.get("id"),
            ad_group_name=ad_group.get("name"),
            criterion_id=criterion.get("criterionId"),
            status=criterion.get("status"),
            keyword=keyword_info.get("text"),
            match_type=keyword_info.get("matchType"),
            quality_score=criterion.get("qualityInfo", {}).get("qualityScore"),
            impressions=metrics.get("impressions"),
            clicks=metrics.get("clicks"),
            ctr=metrics.get("ctr"),
            average_cpc=metrics.get("averageCpc"),
            cost_micros=metrics.get("costMicros"),
            conversions=metrics.get("conversions"),
        )

    def to_dict(self):
        """Convert model to dict for easy serialization."""
        return self.__dict__
