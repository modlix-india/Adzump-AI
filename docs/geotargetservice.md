
#GeoTargetService – Grid-Based Geo Target Discovery (V1)

#PURPOSE

#GeoTargetService is responsible for discovering Google Ads–targetable
#geographic locations (localities, neighborhoods, postal codes) around a given
#product or business location.

This service approximates radius targeting by:
    1. Sampling geography around a center point
    2. Reverse-geocoding sampled points into administrative regions
    3. Converting those regions into Google Ads geoTargetConstants

#HIGH-LEVEL FLOW

#Input:
    - Coordinates (lat/lng)
    OR
    - Area name (string from website summary llm)

#Flow:
    1. Resolve center coordinates
    2. Generate grid points around the center (km-based)
    3. Reverse-geocode each grid point
    4. Extract administrative locations (neighborhood / sublocality / city)
    5. Deduplicate overlapping locations
    6. Verify true distance from center using Haversine formula
    7. Resolve valid locations to Google Ads geoTargetConstants

#Output:
    - TargetPlaceResponse containing resolved geoTargetConstants

#CONFIGURATION & CONSTANTS

#GOOGLE APIs:
    GOOGLE_ADS_API_VERSION = "v20"
    SUGGEST_ENDPOINT       = /geoTargetConstants:suggest
    GEOCODING_API_URL      = https://maps.googleapis.com/maps/api/geocode/json

#DEFAULTS:
    DEFAULT_RADIUS_KM = 15

#GRID SAFETY CONTROLS:
    GRID_STEP_KM             = 5   # Distance between grid samples
    MAX_GRID_POINTS          = 40  # Hard cap to prevent API explosion
    MAX_CONCURRENT_GEOCODE   = 10  # Async request limit
    MIN_DISTANCE_KM          = 2.0 # Deduplication threshold

#These controls exist to:
    - Control Google API cost
    - Limit latency
    - Prevent duplicate or overlapping regions

#PRIMARY ENTRY POINT
#Method:
    suggest_geo_targets(...)
#Signature:
    async def suggest_geo_targets(
        coordinates: Optional[Dict[str, float]],
        area_location: Optional[str],
            radius_km: int
    ) -> TargetPlaceResponse
#Responsibility:
    This method orchestrates the entire geo-target discovery pipeline.

#STEP 1: RESOLVE CENTER COORDINATES

#If coordinates are not provided:
    - Attempt to geocode area_location into lat/lng

#Why:
    All spatial operations depend on a single authoritative center point.

-Methods used:
    - _is_valid_coordinates
    - _geocode_area_location

-If coordinates cannot be resolved, execution stops early.

#STEP 2: GENERATE GRID POINTS
#Method:
    _generate_grid_points(...)

#What it does:
    - Builds a km-based grid around the center point
    - Converts km offsets into latitude/longitude offsets
    - Keeps only points inside a circular radius
    - Enforces MAX_GRID_POINTS hard cap

#Why this exists:
    Google provides NO API to list:
        "All neighborhoods within X kilometers"

#Grid sampling is therefore used as a location discovery heuristic.

#STEP 3: REVERSE GEOCODE GRID POINTS (ASYNC)
#Method:
    _geocode_grid_points_async(...)

#For each grid point:
    - Reverse-geocode using Google Maps
        - Inspect address_components
    - Extract the most specific administrative unit

#Priority order:
    - sublocality_level_1
    - sublocality
    - neighborhood
    - locality

#Country code extraction:
    - Extracted once from the first valid reverse-geocode result
    - Required for Google Ads API

#STEP 4: SPATIAL DEDUPLICATION
#Method:
    _deduplicate_locations(...)

#Removes:
    - Duplicate names (case-insensitive)
    - Locations closer than MIN_DISTANCE_KM

#Why:
    Grid sampling naturally produces overlapping discoveries.

#STEP 5: VERIFY LOCATION CENTERS
#Method:
    _verify_location_centers_async(...)

#For each unique location name:
    - Forward-geocode the location name
    - Retrieve its official center coordinates
    - Measure Haversine distance from product center
    - Keep only locations within radius_km

#Why this step exists:
    Reverse-geocoded grid points are approximate.
    This step ensures distance correctness before Ads resolution.

#STEP 6: RESOLVE TO GOOGLE ADS GEO TARGETS
#Method:
    resolve_locations_batch(...)

#API:
    POST /geoTargetConstants:suggest

#Payload example:
    {
        "countryCode": "IN",
        "locale": "en",
        "locationNames": {
            "names": ["Hulimavu, Bengaluru", "BTM Layout"]
        }
    }

#Why:
    Google Ads only accepts geoTargetConstants, not raw place names.

#STEP 7: PROCESS GOOGLE ADS SUGGESTIONS
#Method:
    _process_suggestions(...)

#Responsibilities:
    - Filter unrelated or noisy Google Ads suggestions
    - Reject overly broad regions (State, Country, District)
    - Enforce exact name matching where required
    - Select exactly one best geoTargetConstant per input term

#Priority scoring:
    Neighborhood > Sublocality > City > Postal Code

#Final Output
#TargetPlaceResponse:
    {
        "locations": [TargetPlaceLocation...],
        "errors": [str...]
    }

#Why:
    This response format allows:
        - Returning multiple valid locations
        - Providing clear error messages
        - Maintaining API consistency
