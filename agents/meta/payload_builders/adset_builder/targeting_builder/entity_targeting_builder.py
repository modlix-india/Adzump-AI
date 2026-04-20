from core.models.meta import Targeting


def build_entity_targeting(targeting: Targeting) -> dict:
    """Transforms interests, behaviors, and demographics into Meta's flexible_spec format."""

    meta_targeting = {}

    # Define the groups we want to map into flexible_spec
    groups = {
        "interests": targeting.interests,
        "behaviors": targeting.behaviors,
        "demographics": targeting.demographics,
    }

    for entities in groups.values():
        if not entities:
            continue

        for entity in entities:
            entity_type = entity.type
            entity_id = entity.id
            entity_name = entity.name

            if entity_type not in meta_targeting:
                meta_targeting[entity_type] = []

            # Targeting model validator already deduplicated IDs across all groups,
            # so we can append directly without additional set-checks here.
            meta_targeting[entity_type].append({"id": entity_id, "name": entity_name})

    if not meta_targeting:
        return {}

    return {"flexible_spec": [meta_targeting]}
