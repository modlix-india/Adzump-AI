from fastapi import HTTPException

from agents.meta.payload_builders.adset_builder.targeting_builder.geo_targeting_builder import build_geo_locations
from agents.meta.payload_builders.adset_builder.targeting_builder.gender_builder import build_gender_targeting
from agents.meta.payload_builders.adset_builder.targeting_builder.locale_builder import build_locale_targeting
from agents.meta.payload_builders.adset_builder.targeting_builder.entity_targeting_builder import build_entity_targeting


def build_targeting(targeting_payload: dict):

    if not targeting_payload:
        raise HTTPException(
            status_code=400,
            detail="Targeting is required"
        )

    meta_targeting_payload = {}

    # GEO TARGETING
    location_list = targeting_payload.get("locations")

    if not location_list:
        raise HTTPException(
            status_code=400,
            detail="Locations are required"
        )

    meta_targeting_payload["geo_locations"] = build_geo_locations(location_list)

    # AGE
    age_min = targeting_payload.get("age_min")
    age_max = targeting_payload.get("age_max")

    if age_min is not None and age_min < 13:
        raise HTTPException(
            status_code=400,
            detail="age_min must be >= 13"
        )

    if age_max is not None and age_max > 65:
        raise HTTPException(
            status_code=400,
            detail="age_max must be <= 65"
        )

    if age_min is not None and age_max is not None and age_min > age_max:
        raise HTTPException(
            status_code=400,
            detail="age_min cannot exceed age_max"
        )

    if age_min is not None:
        meta_targeting_payload["age_min"] = age_min

    if age_max is not None:
        meta_targeting_payload["age_max"] = age_max

    # GENDER
    gender_ids = build_gender_targeting(
        targeting_payload.get("genders")
    )

    if gender_ids:
        meta_targeting_payload["genders"] = gender_ids

    # LOCALES
    locale_ids = build_locale_targeting(
        targeting_payload.get("locales")
    )

    if locale_ids:
        meta_targeting_payload["locales"] = locale_ids

    # ENTITY TARGETING (INTERESTS + DEMOGRAPHICS + BEHAVIORS)
    entity_payload = build_entity_targeting(targeting_payload)

    meta_targeting_payload.update(entity_payload)

    return meta_targeting_payload