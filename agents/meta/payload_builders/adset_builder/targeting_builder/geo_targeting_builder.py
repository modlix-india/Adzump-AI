from fastapi import HTTPException
from agents.meta.payload_builders.constants import VALID_DISTANCE_UNITS, MAX_RADIUS_KM, MAX_RADIUS_MILES, MIN_RADIUS_KM, MIN_RADIUS_MILES

# HELPERS
def _validate_radius(radius, distance_unit, location_type: str):
    """
    Shared radius validation for city and custom location types.
    Validates distance_unit is provided, is valid,
    and radius is within Meta's allowed min/max range.
    """

    # distance_unit is required when radius is provided
    if not distance_unit:
        raise HTTPException(
            status_code=400,
            detail=f"distance_unit is required when radius is provided for {location_type}"
        )

    # distance_unit must be kilometer or mile
    if distance_unit not in VALID_DISTANCE_UNITS:
        raise HTTPException(
            status_code=400,
            detail=f"distance_unit must be one of {VALID_DISTANCE_UNITS}"
        )

    # Validate kilometer range
    if distance_unit == "kilometer":
        if radius < MIN_RADIUS_KM:
            radius = MIN_RADIUS_KM
        if radius > MAX_RADIUS_KM:
            radius = MAX_RADIUS_KM

    # Validate mile range
    if distance_unit == "mile":
        if radius < MIN_RADIUS_MILES:
            radius = MIN_RADIUS_MILES
        if radius > MAX_RADIUS_MILES:
            radius = MAX_RADIUS_MILES

    return radius   

# BUILDER

def build_geo_locations(location_list: list):
    """
    Transforms incoming locations array into Meta compatible geo_locations format.
    Supports: country, city, region, zip, custom location types.
    Strips empty arrays before returning — Meta rejects empty arrays.
    """

    if not location_list:
        raise HTTPException(
            status_code=400,
            detail="Locations are required"
        )

    # Initialize all supported geo location buckets
    geo_payload = {
        "countries": set(),       # set — auto deduplicates country codes
        "cities": [],
        "regions": [],
        "zips": set(),            # set — auto deduplicates zip codes
        "custom_locations": []
    }

    for location in location_list:

        location_type = location.get("type")

        if not location_type:
            raise HTTPException(
                status_code=400,
                detail="Location type is required"
            )

        # COUNTRY
        # Meta expects a list of country codes e.g. ["IN", "US"]
        if location_type == "country":
            country_key = location.get("key")
            if not country_key:
                raise HTTPException(status_code=400, detail="Country key missing")

            # str() cast — Meta always expects string keys
            geo_payload["countries"].add(str(country_key))

        # CITY
        # Meta expects city key with optional radius and distance_unit
        # Defaults to 17km radius if not provided
        elif location_type == "city":
            city_key = location.get("key")
            if not city_key:
                raise HTTPException(status_code=400, detail="City key missing")

            city_payload = {"key": str(city_key)}

            radius = location.get("radius")
            distance_unit = location.get("distance_unit")

            if radius:
                # Validate radius is within Meta's allowed range
                _validate_radius(radius, distance_unit, "city")
                city_payload["radius"] = radius
                city_payload["distance_unit"] = distance_unit
            else:
                # Default radius when not provided
                city_payload["radius"] = MIN_RADIUS_KM
                city_payload["distance_unit"] = "kilometer"

            geo_payload["cities"].append(city_payload)

        # REGION
        # Meta expects region key e.g. state or province
        elif location_type == "region":
            region_key = location.get("key")
            if not region_key:
                raise HTTPException(status_code=400, detail="Region key missing")

            geo_payload["regions"].append({"key": str(region_key)})

        # ZIP
        # Meta expects zip/postal codes as strings
        elif location_type == "zip":
            zip_code = location.get("key")
            if not zip_code:
                raise HTTPException(status_code=400, detail="Zip code missing")

            geo_payload["zips"].add(str(zip_code))

        # CUSTOM LOCATION
        # Meta expects latitude, longitude with optional radius
        # Useful for targeting a specific point on the map
        elif location_type == "custom":
            latitude = location.get("latitude")
            longitude = location.get("longitude")

            if latitude is None or longitude is None:
                raise HTTPException(
                    status_code=400,
                    detail="Custom location requires latitude and longitude"
                )

            custom_location = {
                "latitude": latitude,
                "longitude": longitude
            }

            radius = location.get("radius")
            distance_unit = location.get("distance_unit")

            if radius:
                # Validate radius — same rules as city radius
                _validate_radius(radius, distance_unit, "custom location")
                custom_location["radius"] = radius
                custom_location["distance_unit"] = distance_unit

            geo_payload["custom_locations"].append(custom_location)

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported location type: '{location_type}'. Supported: country, city, region, zip, custom"
            )

    # Convert sets to lists — Meta expects arrays not sets
    geo_payload["countries"] = list(geo_payload["countries"])
    geo_payload["zips"] = list(geo_payload["zips"])

    # Strip empty arrays — Meta rejects keys with empty arrays
    return {
        key: value
        for key, value in geo_payload.items()
        if value
    }