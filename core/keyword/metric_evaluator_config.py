from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetricEvaluatorConfig:
    ctr_threshold: float = 2.0
    quality_score_threshold: int = 4
    cpl_multiplier: float = 1.5
    min_clicks_for_conversions: int = 15
    conversion_rate_threshold: float = 1.0
    critical_click_threshold: int = 50
    critical_cost_threshold: float = 2000.0
    default_max_cpl: float = 2000.0
    default_min_cpl: float = 50.0
    top_performer_percentage: float = 0.2
    performance_weights: dict = field(
        default_factory=lambda: {"efficiency": 0.40, "impressions": 0.30, "conversions": 0.30}
    )


KEYWORD_CONFIG = MetricEvaluatorConfig()


# TODO: group_by_campaign may not belong here. Extracted from metric_performance_evaluator
# to reduce verbosity, but this is a config module. Consider moving to its own module.
def group_by_campaign(entries: list[dict], campaign_mapping: dict) -> list[dict]:
    """Group entries by campaign with business context. Common for all entity types."""
    campaigns: dict[str, dict] = {}
    for entry in entries:
        campaign_id = entry.get("campaign_id", "")
        mapping = campaign_mapping.get(campaign_id)
        if not mapping:
            continue
        group = campaigns.setdefault(campaign_id, {
            "campaign_id": campaign_id,
            "name": entry.get("campaign_name", ""),
            "product_id": mapping["product_id"],
            "business_summary": mapping.get("summary", ""),
            "business_url": mapping.get("business_url", ""),
            "brand_info": mapping.get("brand_info"),
            "unique_features": mapping.get("unique_features", []),
            "entries": [],
        })
        group["entries"].append(entry)
    return list(campaigns.values())
