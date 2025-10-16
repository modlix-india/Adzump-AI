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
    Skip EXCLUDED, ADDED_EXCLUDED, ADDED terms, and None costPerConversion.
    """
    thresholds = get_threshold_values()
    results = []

    for term in search_terms:
        result = evaluate_cost_per_conversion(term, thresholds["cost_per_conversion"])
        if result:
            results.append(result)

    return results
