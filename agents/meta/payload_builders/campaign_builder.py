from fastapi import HTTPException
from .constants import VALID_OBJECTIVES, VALID_STATUSES, VALID_SPECIAL_AD_CATEGORIES
from agents.meta.utils.utils import build_name

def build_campaign_payload(campaign: dict) -> dict:
    """
    Build and validate a Meta Marketing API campaign payload.
    """
    if not isinstance(campaign, dict):
        raise HTTPException(
            status_code=422,
            detail=f"campaign payload must be a dict, got {type(campaign).__name__}"
        )

    # name
    name = campaign.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        raise HTTPException(
            status_code=400,
            detail="name required for campaign"
        )
    name = build_name(name, "campaign")

    # objective
    objective = campaign.get("objective")
    if not objective or not isinstance(objective, str):
        raise HTTPException(
            status_code=400,
            detail="objective required for campaign"
        )
    objective = objective.strip().upper()

    if objective not in VALID_OBJECTIVES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid objective '{objective}' for campaign, must be one of {sorted(VALID_OBJECTIVES)}"
        )

    # status
    raw_status = campaign.get("status", "PAUSED")
    if not isinstance(raw_status, str):
        raise HTTPException(
            status_code=400,
            detail="status required for campaign"
        )
    status = raw_status.strip().upper()
    if status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid status '{status}' for campaign, must be one of {sorted(VALID_STATUSES)}"
        )

    # base payload
    payload = {
        "name": name,
        "objective": objective,
        "status": status,
    }

    # special_ad_category (optional)
    special_category = campaign.get("special_ad_category")
    if special_category:
        if not isinstance(special_category, dict):
            raise HTTPException(
                status_code=400,
                detail="special_ad_category required to be a dict for campaign"
            )

        # type
        category_type = special_category.get("type")
        if not category_type:
            raise HTTPException(
                status_code=400,
                detail="type required for special_ad_category"
            )

        # accept both string and list
        if isinstance(category_type, str):
            category_types = [category_type.strip().upper()]
        elif isinstance(category_type, list):
            if not category_type:
                raise HTTPException(
                    status_code=400,
                    detail="type required for special_ad_category"
                )
            category_types = [c.strip().upper() for c in category_type if isinstance(c, str)]
        else:
            raise HTTPException(
                status_code=400,
                detail="type required for special_ad_category"
            )

        invalid_types = set(category_types) - VALID_SPECIAL_AD_CATEGORIES
        if invalid_types:
            raise HTTPException(
                status_code=400,
                detail=f"invalid type {sorted(invalid_types)} for special_ad_category, "
                       f"must be one of {sorted(VALID_SPECIAL_AD_CATEGORIES)}"
            )

        # countries
        countries = special_category.get("countries")
        if not countries or not isinstance(countries, list) or len(countries) == 0:
            raise HTTPException(
                status_code=400,
                detail="countries required for special_ad_category"
            )

        payload["special_ad_categories"] = category_types
        payload["special_ad_category_country"] = countries

    return payload