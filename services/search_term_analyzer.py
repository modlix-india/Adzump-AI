# TODO: Remove after trust in new search term optimization service (core/services/search_term_analyzer.py)
from services.search_term_metric_evaluators import evaluate_cost_per_conversion

def get_threshold_values():
    """
    Define acceptable threshold values for each metric.
    You can later make this dynamic per client or campaign.
    """
    return {
        "cost_per_conversion": 1000.0
    }


async def analyze_search_term_performance(search_terms: list):
    """
    Classify search terms using metric-based rules.
    - Merge duplicate terms (same term + matchType)
    - Sum metrics for duplicates
    - Skip EXCLUDED, ADDED_EXCLUDED, ADDED terms
    - Only evaluate NONE status terms
    """
    thresholds = get_threshold_values()

    # Step 1: Merge duplicates
    merged_terms = {}
    for term in search_terms:
        term_text = (term.get("searchterm") or "").strip().lower()
        match_type = (term.get("matchType") or "").strip().upper()
        key = (term_text, match_type)

        if key not in merged_terms:
            merged_terms[key] = term
        else:
            existing = merged_terms[key]
            existing_metrics = existing.get("metrics", {})
            new_metrics = term.get("metrics", {})

            # Aggregate numeric metrics
            for metric_key in [
                "impressions",
                "clicks",
                "conversions",
                "costMicros",
                "cost",
            ]:
                existing_metrics[metric_key] = (
                    existing_metrics.get(metric_key, 0)
                    + new_metrics.get(metric_key, 0)
                )

            # Average CTR and CPC
            existing_metrics["ctr"] = (
                existing_metrics.get("ctr", 0) + new_metrics.get("ctr", 0)
            ) / 2
            existing_metrics["averageCpc"] = (
                existing_metrics.get("averageCpc", 0)
                + new_metrics.get("averageCpc", 0)
            ) / 2

            existing["metrics"] = existing_metrics
            


    #Step 2: Evaluate merged terms
    
    results = []
    for term in merged_terms.values():
        result = evaluate_cost_per_conversion(term, thresholds["cost_per_conversion"])
        if result:
            results.append(result)

    return results
