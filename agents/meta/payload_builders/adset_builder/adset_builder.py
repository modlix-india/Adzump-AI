from core.models.meta import (
    AdCreationStage,
    AdSetPayload,
)

from agents.meta.payload_builders.adset_builder.targeting_builder import (
    geo_targeting_builder,
)
from agents.meta.payload_builders.adset_builder.targeting_builder import (
    entity_targeting_builder,
)
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


def build_adset_payload(adset: AdSetPayload, is_dynamic_creative: bool) -> dict:
    """
    Pure transformation layer — no validation.
    """
    promoted_object_payload = (
        adset.promoted_object.to_meta_payload() if adset.promoted_object else None
    )

    adset_dict = adset.model_dump(mode="json", exclude_none=True)
    schedule = adset_dict.get("schedule")
    bidding = adset_dict.get("bidding")

    payload = {
        "name": build_name(adset_dict.get("name"), AdCreationStage.ADSET),
        "destination_type": adset_dict.get("destination_type"),
        "is_dynamic_creative": is_dynamic_creative,
        "start_time": normalize_time(schedule.get("start_time", ""))
        if schedule
        else None,
        "end_time": normalize_time(schedule.get("end_time", "")) if schedule else None,
        "billing_event": bidding.get("billing_event"),
        "optimization_goal": bidding.get("optimization_goal"),
        "bid_strategy": bidding.get("bid_strategy"),
        "bid_amount": bidding.get("bid_amount"),
        "targeting": _build_targeting(adset_dict.get("targeting")),
        "promoted_object": promoted_object_payload,
        "status": adset_dict.get("status"),
        **adset.budget.to_meta_payload(),
        "campaign_id": adset.campaign_id,
    }
    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != ""
    }
