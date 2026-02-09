from dataclasses import dataclass, field
from heapq import nlargest
from statistics import median

import structlog

logger = structlog.get_logger(__name__)


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
SEARCH_TERM_CONFIG = MetricEvaluatorConfig(ctr_threshold=1.5, critical_cost_threshold=1500.0)
AGE_CONFIG = MetricEvaluatorConfig(ctr_threshold=1.0, min_clicks_for_conversions=25)


class MetricPerformanceEvaluator:

    def __init__(self, config: MetricEvaluatorConfig = KEYWORD_CONFIG):
        self.config = config

    def evaluate(self, entries: list) -> tuple[list, list[dict]]:
        """Split entries into good and poor performers with reason."""
        good: list = []
        poor: list[dict] = []
        with_data: list = []

        for entry in entries:
            if entry.impressions == 0:
                d = entry.model_dump()
                d["reason"] = "No impressions - not generating traffic"
                poor.append(d)
            else:
                with_data.append(entry)

        if not with_data:
            return good, poor

        median_cpl = self._calculate_median_cpl(with_data)

        for entry in with_data:
            issues, is_critical = self._identify_performance_issues(entry, median_cpl)
            if len(issues) >= 2 or is_critical:
                d = entry.model_dump()
                d["reason"] = "; ".join(issues)
                poor.append(d)
            else:
                good.append(entry)

        return good, poor

    def extract_top_performers(self, good_entries: list) -> list:
        if not good_entries:
            return []

        max_vals, min_cpl, max_cpl = self._compute_normalization_bounds(good_entries)
        top_count = max(1, int(len(good_entries) * self.config.top_performer_percentage))
        return nlargest(
            top_count,
            good_entries,
            key=lambda e: self._calculate_score(e, max_vals, min_cpl, max_cpl),
        )

    def _calculate_median_cpl(self, entries: list) -> float:
        valid = [e.cpl for e in entries if getattr(e, "cpl", None) and e.cpl > 0]
        return median(valid) if valid else self.config.default_max_cpl

    def _identify_performance_issues(self, entry, median_cpl: float) -> tuple[list[str], bool]:
        cfg = self.config
        issues: list[str] = []
        is_critical = False
        cpl = getattr(entry, "cpl", None)
        conv_rate = getattr(entry, "conv_rate", 0.0)
        quality_score = getattr(entry, "quality_score", None)
        ctr_pct = entry.ctr * 100
        has_enough_clicks = entry.clicks >= cfg.min_clicks_for_conversions

        if entry.conversions == 0:
            if entry.cost >= cfg.critical_cost_threshold:
                issues.append(f"Critical: ₹{entry.cost:.2f} spent with no conversions")
                is_critical = True
            elif entry.clicks >= cfg.critical_click_threshold:
                issues.append(f"Critical: No conversions after {entry.clicks} clicks")
                is_critical = True
            elif has_enough_clicks:
                issues.append("No conversions despite clicks")
        elif cpl and cpl > median_cpl * cfg.cpl_multiplier:
            issues.append(f"High CPL (₹{cpl:.2f} vs ₹{median_cpl:.2f} median)")

        if ctr_pct < cfg.ctr_threshold:
            issues.append(f"Low CTR ({ctr_pct:.1f}%)")
        if entry.clicks == 0 and entry.impressions > 0:
            issues.append(f"No clicks after {entry.impressions} impressions")
        if quality_score and quality_score <= cfg.quality_score_threshold:
            issues.append(f"Low quality score ({quality_score})")
        if conv_rate < cfg.conversion_rate_threshold and has_enough_clicks:
            issues.append(f"Low conversion rate ({conv_rate:.1f}%)")

        return issues, is_critical

    def _compute_normalization_bounds(self, entries: list) -> tuple[dict, float, float]:
        max_imp, max_ctr, max_conv, max_qs = 1.0, 1.0, 1.0, 10.0
        valid_cpls: list[float] = []

        for e in entries:
            max_imp = max(max_imp, e.impressions)
            max_ctr = max(max_ctr, e.ctr)
            max_conv = max(max_conv, e.conversions)
            qs = getattr(e, "quality_score", None)
            if qs:
                max_qs = max(max_qs, qs)
            cpl = getattr(e, "cpl", None)
            if cpl and cpl > 0:
                valid_cpls.append(cpl)

        max_vals = {"impressions": max_imp, "ctr": max_ctr, "conversions": max_conv, "quality": max_qs}
        min_cpl = min(valid_cpls) if valid_cpls else self.config.default_min_cpl
        max_cpl = (
            min(max(valid_cpls), self.config.default_max_cpl * 2)
            if valid_cpls
            else self.config.default_max_cpl
        )
        return max_vals, min_cpl, max_cpl

    def _calculate_score(self, entry, max_vals: dict, min_cpl: float, max_cpl: float) -> float:
        w = self.config.performance_weights
        cpl = getattr(entry, "cpl", None)
        quality_score = getattr(entry, "quality_score", None)

        imp_score = (entry.impressions / max_vals["impressions"]) * 100
        ctr_score = (entry.ctr / max_vals["ctr"]) * 100
        conv_score = (entry.conversions / max_vals["conversions"]) * 100
        quality_norm = (quality_score / max_vals["quality"] * 100) if quality_score else 50

        if cpl and cpl > 0 and max_cpl > min_cpl:
            cpl_score = (1 - (min(cpl, max_cpl) - min_cpl) / (max_cpl - min_cpl)) * 100
        else:
            cpl_score = 50

        efficiency = (ctr_score + quality_norm + cpl_score) / 3
        return efficiency * w["efficiency"] + imp_score * w["impressions"] + conv_score * w["conversions"]
