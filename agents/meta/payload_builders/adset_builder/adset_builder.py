from core.models.meta import PromotedObjectType, BudgetType, AdCreationStage

from agents.meta.payload_builders.adset_builder.targeting_builder import (
    geo_targeting_builder,
)
from agents.meta.payload_builders.adset_builder.targeting_builder import (
    entity_targeting_builder,
)
from agents.meta.payload_builders.constants import INR_TO_MINOR_UNIT
from agents.meta.utils.payload_helpers import build_name, normalize_time
from structlog import get_logger


logger = get_logger(__name__)


def _build_targeting(targeting: dict) -> dict:
    meta_targeting = {}

    meta_targeting["geo_locations"] = geo_targeting_builder.build_geo_locations(
        targeting.get("locations")
    )

    if "age_min" in targeting:
        meta_targeting["age_min"] = targeting["age_min"]

    if "age_max" in targeting:
        meta_targeting["age_max"] = targeting["age_max"]

    if targeting.get("genders"):
        gender_map = {"MALE": 1, "FEMALE": 2}
        meta_targeting["genders"] = list({gender_map[g] for g in targeting["genders"]})

    if targeting.get("locales"):
        meta_targeting["locales"] = list({loc["key"] for loc in targeting["locales"]})

    entity_payload = entity_targeting_builder.build_entity_targeting(targeting)
    meta_targeting.update(entity_payload)

    return meta_targeting


def map_promoted_object(promoted_object: dict):
    if not promoted_object:
        return None

    object_type = promoted_object.get("type")

    if object_type == PromotedObjectType.PAGE:
        return {"page_id": str(promoted_object.get("page_id"))}

    if object_type == PromotedObjectType.PIXEL:
        return {
            "pixel_id": str(promoted_object.get("pixel_id")),
            "custom_event_type": promoted_object.get("event"),
        }

    if object_type == PromotedObjectType.APP:
        return {
            "application_id": str(promoted_object.get("application_id")),
            "object_store_url": promoted_object.get("object_store_url"),
        }

    return None


def normalize_budget(budget: dict | None) -> dict:
    """
    Only transformation — assumes validation already done in model.
    Converts INR → Meta minor units.
    """
    amount = budget.get("amount")
    budget_type = budget.get("type")

    minor_units = int(amount * INR_TO_MINOR_UNIT)

    if budget_type == BudgetType.DAILY:
        return {"daily_budget": minor_units}

    if budget_type == BudgetType.LIFETIME:
        return {"lifetime_budget": minor_units}

    return {}


def build_adset_payload(adset: dict, is_dynamic_creative: bool) -> dict:
    """
    Pure transformation layer — no validation.
    """
    schedule = adset.get("schedule")
    bidding = adset.get("bidding")

    payload = {
        "name": build_name(adset.get("name"), AdCreationStage.ADSET),
        "destination_type": adset.get("destination_type"),
        "is_dynamic_creative": is_dynamic_creative,
        "start_time": normalize_time(schedule.get("start_time", ""))
        if schedule
        else None,
        "end_time": normalize_time(schedule.get("end_time", "")) if schedule else None,
        "billing_event": bidding.get("billing_event"),
        "optimization_goal": bidding.get("optimization_goal"),
        "bid_strategy": bidding.get("bid_strategy"),
        "bid_amount": bidding.get("bid_amount"),
        "targeting": _build_targeting(adset.get("targeting")),
        "promoted_object": map_promoted_object(adset.get("promoted_object")),
        "status": adset.get("status"),
        **normalize_budget(adset.get("budget")),
    }
    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != ""
    }
