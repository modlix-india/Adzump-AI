from services.thresholds_service import get_threshold_values
from services.metric_evaluators import evaluate_cost_per_conversion


async def classify_search_terms(search_terms: list):
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

