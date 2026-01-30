from typing import List, Dict, Any


def calculate_performance_metrics(
    metrics_data: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Calculates derived performance metrics (CPA, CTR, CPC, Cost) from raw Google Ads metrics.
    Converts micros to standard currency units.
    """
    calculated = []
    for entry in metrics_data:
        metrics = entry.get("metrics", {})
        cost_micros = float(metrics.get("costMicros", 0))
        clicks = float(metrics.get("clicks", 0))
        impressions = float(metrics.get("impressions", 0))
        conversions = float(metrics.get("conversions", 0))

        cost = cost_micros / 1_000_000

        cpa = cost / conversions if conversions > 0 else 0.0
        ctr = (clicks / impressions * 100) if impressions > 0 else 0.0
        cpc = cost / clicks if clicks > 0 else 0.0

        entry["calculated_metrics"] = {
            "cost": round(cost, 2),
            "CPA": round(cpa, 2),
            "CTR": round(ctr, 2),
            "CPC": round(cpc, 2),
        }

        calculated.append(entry)

    return calculated
