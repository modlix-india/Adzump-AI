# TODO: Remove after trust in new search term optimization service (core/services/search_term_analyzer.py)
def evaluate_cost_per_conversion(term_data, threshold):
    """
    Evaluate costPerConversion vs. threshold.
    Only evaluate terms with status == NONE.
    """
    status = str(term_data.get("status") or "").strip().upper()
    if status != "NONE":
        return None

    metrics = term_data.get("metrics", {})
    raw_value = metrics.get("costPerConversion")

    if raw_value is None:
        return None

    try:
        value = float(raw_value)
        if value > 10000:
            value = round(value / 1_000_000, 2)
    except (TypeError, ValueError):
        return None

    ad_group_id = term_data.get("adGroupId")
    match_type = term_data.get("matchType")

    base_result = {
        "term": term_data.get("searchterm")
        or term_data.get("searchTermView", {}).get("searchTerm"),
        "status": status,
        "adGroupId": ad_group_id,
        "matchType": match_type,
        "metrics": {**metrics, "costPerConversion": value},
    }

    if value < threshold:
        return {
            **base_result,
            "classification": "Positive",
            "reason": f"Cost per conversion is {value} (below threshold {threshold}).",
            "recommendation": f"Good performance — cost per conversion is affordable at {value}.",
        }

    return {
        **base_result,
        "classification": "Negative",
        "reason": f"Cost per conversion is {value} (above threshold {threshold}).",
        "recommendation": f"High cost ({value}) — consider pausing or optimizing this term.",
    }
