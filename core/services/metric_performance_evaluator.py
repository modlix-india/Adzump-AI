from heapq import nlargest
from statistics import median

import structlog

from core.services.metric_evaluator_config import MetricEvaluatorConfig, KEYWORD_CONFIG

logger = structlog.get_logger(__name__)


class MetricPerformanceEvaluator:
    def __init__(self, config: MetricEvaluatorConfig = KEYWORD_CONFIG):
        self.config = config

    def evaluate(self, entries: list[dict]) -> list[dict]:
        """Classify entries with strength: good, poor."""
        results: list[dict] = []
        with_data: list[dict] = []

        for entry in entries:
            if entry["metrics"]["impressions"] == 0:
                results.append(
                    {
                        **entry,
                        "strength": "poor",
                        "is_critical": True,
                        "reason": "No impressions - not generating traffic",
                    }
                )
            else:
                with_data.append(entry)

        if not with_data:
            return results

        median_cpl = self._calculate_median_cpl(with_data)

        for entry in with_data:
            issues, is_critical = self._identify_performance_issues(entry, median_cpl)
            if len(issues) >= 2 or is_critical:
                results.append(
                    {
                        **entry,
                        "strength": "poor",
                        "is_critical": is_critical,
                        "reason": "; ".join(issues),
                    }
                )
            else:
                results.append({**entry, "strength": "good"})

        logger.info(
            "performance_evaluation",
            total=len(results),
            good=sum(1 for e in results if e["strength"] == "good"),
        )
        return results

    def mark_top_performers(self, entries: list[dict]) -> None:
        """Upgrade top good entries strength to 'top'."""
        good = [e for e in entries if e.get("strength") == "good"]
        if not good:
            return
        top_set = set(map(id, self._rank_top_entries(good)))
        for e in entries:
            if id(e) in top_set:
                e["strength"] = "top"

    def _calculate_median_cpl(self, entries: list[dict]) -> float:
        valid = [e["metrics"]["cpl"] for e in entries if e["metrics"].get("cpl")]
        return median(valid) if valid else self.config.default_max_cpl

    def _identify_performance_issues(
        self, entry: dict, median_cpl: float
    ) -> tuple[list[str], bool]:
        cfg = self.config
        m = entry["metrics"]
        issues: list[str] = []
        is_critical = False
        cpl = m.get("cpl")
        conv_rate = m.get("conv_rate", 0.0)
        quality_score = entry.get("quality_score")
        has_enough_clicks = m["clicks"] >= cfg.min_clicks_for_conversions

        if m["conversions"] == 0:
            if m["cost"] >= cfg.critical_cost_threshold:
                issues.append(f"Critical: ₹{m['cost']:.2f} spent with no conversions")
                is_critical = True
            elif m["clicks"] >= cfg.critical_click_threshold:
                issues.append(f"Critical: No conversions after {m['clicks']} clicks")
                is_critical = True
            elif has_enough_clicks:
                issues.append("No conversions despite clicks")
        elif cpl and cpl > median_cpl * cfg.cpl_multiplier:
            issues.append(f"High CPL (₹{cpl:.2f} vs ₹{median_cpl:.2f} median)")

        if m["ctr"] < cfg.ctr_threshold:
            issues.append(f"Low CTR ({m['ctr']:.1f}%)")
        if m["clicks"] == 0 and m["impressions"] > 0:
            issues.append(f"No clicks after {m['impressions']} impressions")
        if quality_score and quality_score <= cfg.quality_score_threshold:
            issues.append(f"Low quality score ({quality_score})")
        if conv_rate < cfg.conversion_rate_threshold and has_enough_clicks:
            issues.append(f"Low conversion rate ({conv_rate:.1f}%)")

        return issues, is_critical

    def _rank_top_entries(self, entries: list[dict]) -> list[dict]:
        """Return top N entries by performance score."""
        max_vals, min_cpl, max_cpl = self._compute_normalization_bounds(entries)
        top_count = max(1, int(len(entries) * self.config.top_performer_percentage))
        return nlargest(
            top_count,
            entries,
            key=lambda e: self._calculate_score(e, max_vals, min_cpl, max_cpl),
        )

    def _compute_normalization_bounds(
        self, entries: list[dict]
    ) -> tuple[dict, float, float]:
        max_imp, max_ctr, max_conv, max_qs = 1.0, 1.0, 1.0, 10.0
        valid_cpls: list[float] = []
        for e in entries:
            m = e["metrics"]
            max_imp = max(max_imp, m["impressions"])
            max_ctr = max(max_ctr, m["ctr"])
            max_conv = max(max_conv, m["conversions"])
            qs = e.get("quality_score")
            if qs:
                max_qs = max(max_qs, qs)
            cpl = m.get("cpl")
            if cpl and cpl > 0:
                valid_cpls.append(cpl)

        max_vals = {
            "impressions": max_imp,
            "ctr": max_ctr,
            "conversions": max_conv,
            "quality": max_qs,
        }
        cfg = self.config
        min_cpl = min(valid_cpls) if valid_cpls else cfg.default_min_cpl
        max_cpl = (
            min(max(valid_cpls), cfg.default_max_cpl * 2)
            if valid_cpls
            else cfg.default_max_cpl
        )
        return max_vals, min_cpl, max_cpl

    def _calculate_score(
        self, entry: dict, max_vals: dict, min_cpl: float, max_cpl: float
    ) -> float:
        w = self.config.performance_weights
        m = entry["metrics"]
        cpl = m.get("cpl")
        qs = entry.get("quality_score")

        imp_score = (m["impressions"] / max_vals["impressions"]) * 100
        ctr_score = (m["ctr"] / max_vals["ctr"]) * 100
        conv_score = (m["conversions"] / max_vals["conversions"]) * 100
        qs_score = (qs / max_vals["quality"] * 100) if qs else 50
        cpl_score = (
            (1 - (min(cpl, max_cpl) - min_cpl) / (max_cpl - min_cpl)) * 100
            if cpl and max_cpl > min_cpl
            else 50
        )

        efficiency = (ctr_score + qs_score + cpl_score) / 3
        return (
            efficiency * w["efficiency"]
            + imp_score * w["impressions"]
            + conv_score * w["conversions"]
        )
