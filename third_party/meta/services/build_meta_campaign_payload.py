def build_meta_campaign_payload(
    business_name: str,
    budget: float,
    duration_days: int,
    ad_copy: dict
):
    variation = (ad_copy.get("variations") or [{}])[0]

    return {
        "campaign": {
            "name": f"{business_name} Meta Campaign",
            "objective": "LEADS",
            "status": "PAUSED"
        },
        "ad_set": {
            "daily_budget": int(budget * 100),
            "duration_days": duration_days
        },
        "ad": {
            "primary_text": variation.get("primary_text"),
            "headline": variation.get("headline"),
            "description": variation.get("description")
        }
    }