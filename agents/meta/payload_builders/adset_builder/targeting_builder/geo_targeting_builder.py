from core.models.meta import Location
from core.models.meta_constants import MIN_RADIUS_KM, DEFAULT_DISTANCE_UNIT


def build_geo_locations(locations: list[Location]):
    """Transform Location models into Meta compatible geo_locations format.
 
    Use an internal set-based approach for automatic deduplication.
    """

    if not locations:
        raise ValueError("Locations are required")

    temp_storage = {
        "countries": set(),
        "cities": {},  # key -> Location
        "regions": set(),
        "zips": set(),
        "neighborhoods": set(),
        "custom": {},  # coords -> Location
    }

    for location in locations:
        match location.type:
            case "country":
                temp_storage["countries"].add(location.key)

            case "city":
                temp_storage["cities"][location.key] = location

            case "region":
                temp_storage["regions"].add(location.key)

            case "zip":
                temp_storage["zips"].add(location.key)

            case "neighborhood":
                temp_storage["neighborhoods"].add(location.key)

            case "custom":
                if location.latitude is None or location.longitude is None:
                    raise ValueError("Custom location requires latitude and longitude")
                coords = (location.latitude, location.longitude)
                temp_storage["custom"][coords] = location

            case _:
                raise ValueError(
                    f"Unsupported location type: '{location.type}'. "
                    "Supported: country, city, region, zip, custom, neighborhood"
                )

    return _format_geo_payload(temp_storage)


def _format_geo_payload(temp_storage: dict) -> dict:
    """Transform internal set-based storage into the final Meta-compatible JSON structure."""
    geo_payload = {}

    if temp_storage["countries"]:
        geo_payload["countries"] = list(temp_storage["countries"])

    if temp_storage["cities"]:
        geo_payload["cities"] = []
        for key, loc in temp_storage["cities"].items():
            item = {"key": key}
            _apply_radius_and_unit(item, loc)
            geo_payload["cities"].append(item)

    if temp_storage["regions"]:
        geo_payload["regions"] = [{"key": k} for k in temp_storage["regions"]]

    if temp_storage["zips"]:
        geo_payload["zips"] = [{"key": k} for k in temp_storage["zips"]]

    if temp_storage["neighborhoods"]:
        geo_payload["neighborhoods"] = [
            {"key": k} for k in temp_storage["neighborhoods"]
        ]

    if temp_storage["custom"]:
        geo_payload["custom_locations"] = []
        for coords, loc in temp_storage["custom"].items():
            item = {"latitude": coords[0], "longitude": coords[1]}
            _apply_radius_and_unit(item, loc)
            geo_payload["custom_locations"].append(item)

    return geo_payload


def _apply_radius_and_unit(payload: dict, location: Location):
    """Apply radius and distance unit to a location payload, falling back to MIN_RADIUS_KM (17km)."""
    if location.radius:
        payload["radius"] = location.radius
        payload["distance_unit"] = location.distance_unit or DEFAULT_DISTANCE_UNIT
    else:
        payload["radius"] = MIN_RADIUS_KM
        payload["distance_unit"] = DEFAULT_DISTANCE_UNIT
