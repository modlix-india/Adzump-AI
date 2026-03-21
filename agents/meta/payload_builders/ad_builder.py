from agents.meta.utils.utils import build_name
from fastapi import HTTPException

def build_ad_payload(ad: dict, destination_type: str = None, lead_gen_form_id: str = None) -> dict:

    creative_payload = {}  # creative_id injected later

    ad_payload = {
        "name":     build_name(ad.get("name"), "ad"),
        "creative": creative_payload,
        "status":   ad.get("status", "PAUSED")
    }

    # For Lead Ads — lead_gen_form_id goes at TOP LEVEL of ad, not inside creative
    if destination_type == "ON_AD":
        if not lead_gen_form_id or not str(lead_gen_form_id).strip():
            raise HTTPException(
                status_code=400,
                detail="lead_gen_form_id is required for ON_AD (Lead Ads)."
            )
        ad_payload["lead_gen_form_id"] = lead_gen_form_id

    return ad_payload