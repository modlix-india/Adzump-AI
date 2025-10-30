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
    impressions: int = 0
    clicks: int = 0
    ctr: float = 0.0
    average_cpc: float = 0.0
    cost_micros: int = 0
    conversions: float = 0.0

    @classmethod
    def from_google_row(cls, row: dict) -> "Keyword":
        """Parse a Google Ads API row into a Keyword model."""

        def _safe_int(v):
            try:
                return int(float(v))
            except Exception:
                return 0

        def _safe_float(v):
            try:
                return float(v)
            except Exception:
                return 0.0

        def normalize(t: str) -> str:
            if not t:
                return ""
            t = t.lower().strip()
            for ch in ["-", "_", "+", ".", ","]:
                t = t.replace(ch, " ")
            return " ".join(t.split())

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
            keyword=normalize(keyword_info.get("text")),
            match_type=keyword_info.get("matchType"),
            quality_score=criterion.get("qualityInfo", {}).get("qualityScore"),
            impressions=_safe_int(metrics.get("impressions")),
            clicks=_safe_int(metrics.get("clicks")),
            ctr=_safe_float(metrics.get("ctr")),
            average_cpc=_safe_float(metrics.get("averageCpc")),
            cost_micros=_safe_int(metrics.get("costMicros")),
            conversions=_safe_float(metrics.get("conversions")),
        )

    def to_dict(self):
        """Convert model to plain dict (useful for JSON response)."""
        return self.__dict__
