from fastapi import HTTPException

from agents.meta.payload_builders.constants import FIXED_CATEGORIES, NON_DEMOGRAPHIC_TYPES


def build_entity_targeting(targeting_payload: dict) -> dict:
    """
    Validates, expands and transforms interests, behaviors, demographics
    into Meta compatible flexible_spec format in a single pass.
    Returns empty dict if no entity targeting is provided.
    """

    meta_targeting = {}

    for category_name in FIXED_CATEGORIES:

        category_entities = targeting_payload.get(category_name)

        if not category_entities:
            continue

        for entity in category_entities:

            entity_type = entity.get("type")
            entity_id = str(entity.get("id"))
            entity_name = entity.get("name")

            # Validate interests and behaviors type matches category name
            if category_name in NON_DEMOGRAPHIC_TYPES and entity_type != category_name:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid type '{entity_type}' found in '{category_name}'. Expected type '{category_name}'"
                )

            # Validate demographics doesn't contain interests or behaviors
            if category_name == "demographics" and entity_type in NON_DEMOGRAPHIC_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid type '{entity_type}' found in 'demographics'. '{entity_type}' must be in its own array"
                )

            # Dynamically initialize targeting group if not present
            if entity_type not in meta_targeting:
                meta_targeting[entity_type] = {
                    "processed_ids": set(),
                    "targeting_entities": []
                }

            targeting_group = meta_targeting[entity_type]

            # Deduplicate and append in same step
            if entity_id not in targeting_group["processed_ids"]:
                targeting_group["processed_ids"].add(entity_id)
                targeting_group["targeting_entities"].append({
                    "id": entity_id,
                    "name": entity_name
                })

    # No entity targeting provided — return empty dict
    # flexible_spec will not be added to the payload
    if not meta_targeting:
        return {}

    # Build single flexible_spec object with all entity types
    flexible_spec_object = {
        entity_type: targeting_group["targeting_entities"]
        for entity_type, targeting_group in meta_targeting.items()
    }

    return {"flexible_spec": [flexible_spec_object]}