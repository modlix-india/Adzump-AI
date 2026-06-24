from core.models.meta import (
    AdCreationStage,
    AdSetPayload,
    Targeting,
)

from agents.meta.payload_builders.adset_builder.targeting_builder import (
    geo_targeting_builder,
    entity_targeting_builder,
)

from core.models import meta_constants
from agents.meta.utils.payload_helpers import build_name, normalize_time


def _build_targeting(targeting: Targeting) -> dict:
    """Assemble the Meta targeting dictionary including geo, age, gender, and interests."""
    meta_targeting = {}

    meta_targeting["geo_locations"] = geo_targeting_builder.build_geo_locations(
        targeting.locations
    )

    if targeting.age_min is not None:
        meta_targeting["age_min"] = targeting.age_min

    if targeting.age_max is not None:
        meta_targeting["age_max"] = targeting.age_max

    if targeting.genders:
        gender_map = {
            "MALE": meta_constants.GENDER_MALE_VALUE,
            "FEMALE": meta_constants.GENDER_FEMALE_VALUE,
        }
        meta_targeting["genders"] = list(
            {gender_map[g.value] for g in targeting.genders}
        )

    if targeting.locales:
        meta_targeting["locales"] = list({loc.key for loc in targeting.locales})

    entity_payload = entity_targeting_builder.build_entity_targeting(targeting)
    meta_targeting.update(entity_payload)

    meta_targeting["targeting_automation"] = {"advantage_audience": 0}

    return meta_targeting


def build_adset_payload(adset: AdSetPayload, is_dynamic_creative: bool) -> dict:
    """Transform AdSet model into Meta AdSet API payload (including budget and targeting)."""
    promoted_object_payload = (
        adset.promoted_object.to_meta_payload() if adset.promoted_object else None
    )

    payload = {
        "name": build_name(adset.name, AdCreationStage.ADSET),
        "destination_type": adset.destination_type.value,
        "is_dynamic_creative": is_dynamic_creative,
        "start_time": normalize_time(adset.schedule.start_time)
        if adset.schedule
        else None,
        "end_time": normalize_time(adset.schedule.end_time)
        if adset.schedule and adset.schedule.end_time
        else None,
        "billing_event": adset.bidding.billing_event.value,
        "optimization_goal": adset.bidding.optimization_goal.value,
        "bid_strategy": adset.bidding.bid_strategy.value,
        "bid_amount": adset.bidding.bid_amount,
        "targeting": _build_targeting(adset.targeting),
        "promoted_object": promoted_object_payload,
        "status": adset.status.value,
        **adset.budget.to_meta_payload(),
        "campaign_id": adset.campaign_id,
    }
    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != ""
    }
