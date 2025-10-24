def evaluate_cost_per_conversion(term_data, threshold):
    """
    Evaluate costPerConversion vs. threshold.
    Converts micros → readable currency and skips invalid or handled terms.
    """
    status = (
        term_data.get("status")
        or term_data.get("searchTermView", {}).get("status")
        or ""
    ).strip().upper()

    if status in ["EXCLUDED", "ADDED_EXCLUDED", "ADDED"]:
        return None

    metrics = term_data.get("metrics", {})
    raw_value = metrics.get("costPerConversion") or metrics.get("cost_per_conversion")

    if raw_value is None:
        return None

    try:
        value = round(float(raw_value) / 1_000_000, 2)
    except (TypeError, ValueError):
        return None

    # Extract optional fields
    ad_group_id = term_data.get("adGroupId")
    match_type = term_data.get("matchType")

    # Common base result
    base_result = {
        "term": term_data.get("searchterm") or term_data.get("searchTermView", {}).get("searchTerm"),
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
    else:
        return {
            **base_result,
            "classification": "Negative",
            "reason": f"Cost per conversion is {value} (above threshold {threshold}).",
            "recommendation": f"High cost ({value}) — consider pausing or optimizing this term.",
        }
