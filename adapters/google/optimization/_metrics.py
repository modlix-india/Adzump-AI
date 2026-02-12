from utils.helpers import micros_to_rupees


def build_metrics(raw: dict) -> dict:
    clicks = int(raw.get("clicks", 0))
    conversions = float(raw.get("conversions", 0))
    cost = micros_to_rupees(raw.get("costMicros", 0))
    cpl_raw = float(raw.get("costPerConversion", 0))

    return {
        "impressions": int(raw.get("impressions", 0)),
        "clicks": clicks,
        "conversions": conversions,
        "cost": cost,
        "ctr": round(float(raw.get("ctr", 0)) * 100, 2),
        "average_cpc": micros_to_rupees(raw.get("averageCpc", 0)),
        "cpl": micros_to_rupees(cpl_raw) if cpl_raw > 0 else None,
        "conv_rate": round(conversions / clicks * 100, 2) if clicks > 0 else 0.0,
    }
