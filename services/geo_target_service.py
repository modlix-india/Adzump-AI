import os
import httpx
from typing import List, Dict, Optional
from structlog import get_logger  # type: ignore
import urllib.parse
from models.maps_model import TargetPlaceLocation, TargetPlaceResponse
from oserver.services.connection import fetch_google_api_token_simple

logger = get_logger(__name__)


class GeoTargetService:
    """
    Service for resolving locations to Google Ads geoTargetConstants.
    Handles reverse geocoding, nearby places search, and batch resolution.
    """

    GOOGLE_ADS_API_VERSION = "v20"
    SUGGEST_ENDPOINT = f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}/geoTargetConstants:suggest"
    GEOCODING_API_URL = "https://maps.googleapis.com/maps/api/geocode/json"
    PLACES_API_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    HTTP_TIMEOUT = 30.0
    DEFAULT_RADIUS_KM = 30
    # Address component types to extract (excluding country)
    ADDRESS_TYPES = [
        "locality",  # City
        "administrative_area_level_2",  # District
        "administrative_area_level_1",  # State
    ]

    def __init__(self, client_code: str):
        self._google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        self._developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
        # self._access_token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN")
        try:
            self._access_token = fetch_google_api_token_simple(client_code)
        except Exception as e:
            logger.warning(f"Failed to fetch Google API token: {e}. Geo-targeting will be limited.")
            self._access_token = None

    _client: Optional[httpx.AsyncClient] = None

    @classmethod
    async def _get_client(cls) -> httpx.AsyncClient:
        """Get or create shared httpx client."""
        if cls._client is None or cls._client.is_closed:
            cls._client = httpx.AsyncClient(timeout=cls.HTTP_TIMEOUT)
        return cls._client

    @classmethod
    async def close_client(cls):
        """Close the shared httpx client."""
        if cls._client and not cls._client.is_closed:
            await cls._client.aclose()
            logger.info("GeoTargetService http client closed")
        cls._client = None

    # ========== PUBLIC METHODS ==========

    async def suggest_geo_targets(
        self,
        coordinates: Optional[Dict[str, float]] = None,
        interested_locations: Optional[List[str]] = None,
        area_location: Optional[str] = None,
        radius_km: int = DEFAULT_RADIUS_KM,
    ) -> TargetPlaceResponse:
        """
        Suggest geo targets from multiple sources:
        1. Reverse geocode coordinates → city/state
        2. Find nearby places within radius
        3. Resolve interested_locations from LLM

        All combined, deduplicated, and resolved to geoTargetConstants.
        """
        all_locations: List[str] = []
        product_location: Optional[str] = None

        # From coordinates
        if self._is_valid_coordinates(coordinates):
            lat, lng = coordinates["lat"], coordinates["lng"]
            geocoded = await self.reverse_geocode(lat, lng)
            if geocoded:
                product_location = geocoded[0]
                all_locations.extend(geocoded)
            nearby = await self.find_nearby_places(lat, lng, radius_km)
            all_locations.extend(nearby)

        # From LLM interested_locations
        if interested_locations:
            all_locations.extend(interested_locations)
            # Also get postal codes for interested locations
            logger.info(
                f"Looking up postal codes for {len(interested_locations)} locations..."
            )
            for location in interested_locations:
                postal_code = await self.get_postal_code(location, area_location)
                if postal_code:
                    all_locations.append(postal_code)

        # Deduplicate while preserving order
        unique_locations = list(dict.fromkeys(all_locations))

        if not unique_locations:
            logger.info("No locations to resolve")
            return TargetPlaceResponse(
                locations=[], unresolved=[], product_location=product_location
            )

        # Resolve to geoTargetConstants
        result = await self.resolve_locations_batch(
            locations=unique_locations, area_location=area_location
        )

        # Apply hierarchical selection (only keep most specific tier)
        selected_locations = self._select_most_specific_tier(result.locations)
        result.locations = selected_locations
        result.product_location = product_location

        logger.info(
            f"Suggested {len(result.locations)} geo targets (after hierarchical selection)"
        )
        return result

    async def resolve_locations_batch(
        self,
        locations: List[str],
        country_code: Optional[str] = None,
        locale: str = "en",
        area_location: Optional[str] = None,
    ) -> TargetPlaceResponse:
        """Resolve location names to geoTargetConstants using Google Ads API."""
        if not self._has_google_ads_credentials():
            logger.error("Missing Google Ads credentials")
            return TargetPlaceResponse(locations=[], unresolved=locations)

        # Infer country code from area_location if not provided
        if not country_code:
            country_code = await self._infer_country_code(area_location)
            logger.info(
                f"Inferred country_code: {country_code} from area_location: {area_location}"
            )

        headers = self._get_google_ads_headers()
        payload = {
            "locale": locale,
            "countryCode": country_code,
            "locationNames": {"names": locations},
        }

        resolved: List[TargetPlaceLocation] = []
        resolved_names: set = set()

        try:
            client = await self._get_client()
            response = await client.post(
                self.SUGGEST_ENDPOINT, headers=headers, json=payload
            )

            if response.status_code != 200:
                logger.error(
                    f"Google Ads API error: {response.status_code} - {response.text}"
                )
                return TargetPlaceResponse(locations=[], unresolved=locations)

            data = response.json()
            suggestions = data.get("geoTargetConstantSuggestions", [])
            logger.info(
                f"Google Ads API returned {len(suggestions)} suggestions for {locations}"
            )

            resolved, resolved_names = self._process_suggestions(
                suggestions, area_location
            )

        except Exception as e:
            logger.exception(f"Batch resolution failed: {e}")
            return TargetPlaceResponse(locations=[], unresolved=locations)

        unresolved = [loc for loc in locations if loc.lower() not in resolved_names]

        logger.info(f"Resolved {len(resolved)} locations, {len(unresolved)} unresolved")
        return TargetPlaceResponse(locations=resolved, unresolved=unresolved)

    async def reverse_geocode(self, lat: float, lng: float) -> List[str]:
        """Reverse geocode coordinates to get city, state, country names."""
        if not self._google_maps_api_key:
            logger.error("Missing GOOGLE_MAPS_API_KEY")
            return []

        url = f"{self.GEOCODING_API_URL}?latlng={lat},{lng}&key={self._google_maps_api_key}"

        try:
            client = await self._get_client()
            response = await client.get(url)

            if response.status_code != 200:
                logger.error(f"Geocoding API error: {response.status_code}")
                return []

            data = response.json()
            if data.get("status") != "OK":
                logger.warning(f"Geocoding failed: {data.get('status')}")
                return []

            locations = self._extract_locations_from_geocode(data)
            logger.info(f"Reverse geocoded {lat},{lng} → {locations}")
            return locations

        except Exception as e:
            logger.exception(f"Reverse geocoding failed: {e}")
            return []

    async def find_nearby_places(
        self, lat: float, lng: float, radius_km: int = DEFAULT_RADIUS_KM
    ) -> List[str]:
        """Find nearby localities within radius using Google Places API."""
        if not self._google_maps_api_key:
            logger.error("Missing GOOGLE_MAPS_API_KEY")
            return []

        radius_meters = radius_km * 1000
        url = (
            f"{self.PLACES_API_URL}"
            f"?location={lat},{lng}&radius={radius_meters}"
            f"&type=locality&key={self._google_maps_api_key}"
        )

        try:
            client = await self._get_client()
            response = await client.get(url)

            if response.status_code != 200:
                logger.error(f"Places API error: {response.status_code}")
                return []

            data = response.json()
            if data.get("status") not in ["OK", "ZERO_RESULTS"]:
                logger.warning(f"Places API failed: {data.get('status')}")
                return []

            places = self._extract_place_names(data)
            logger.info(f"Found {len(places)} nearby places within {radius_km}km")
            return places

        except Exception as e:
            logger.exception(f"Nearby places search failed: {e}")
            return []

    async def get_postal_code(
        self, location_name: str, area_location: str = None
    ) -> Optional[str]:
        """
        Get postal code for a location name using Google Geocoding API.
        Returns the postal code if found, otherwise None.
        """
        if not self._google_maps_api_key:
            logger.error("Missing GOOGLE_MAPS_API_KEY")
            return None

        # Build search query with area context
        query = f"{location_name}, {area_location}" if area_location else location_name
        url = (
            f"{self.GEOCODING_API_URL}?address={query}&key={self._google_maps_api_key}"
        )

        try:
            client = await self._get_client()
            response = await client.get(url)

            if response.status_code != 200:
                logger.error(f"Geocoding API error: {response.status_code}")
                return None

            data = response.json()
            if data.get("status") != "OK":
                logger.debug(f"No postal code found for {location_name}")
                return None

            # Extract postal code from first result
            for result in data.get("results", []):
                for component in result.get("address_components", []):
                    if "postal_code" in component.get("types", []):
                        postal_code = component.get("long_name", "")
                        logger.info(
                            f"Found postal code for {location_name}: {postal_code}"
                        )
                        return postal_code

            logger.debug(f"No postal code in geocoding result for {location_name}")
            return None

        except Exception as e:
            logger.exception(f"Postal code lookup failed for {location_name}: {e}")
            return None

    # ========== PRIVATE HELPER METHODS ==========

    async def _infer_country_code(self, area_location: Optional[str]) -> str:
        """
        Infer country code from area_location using Google Geocoding API.
        Returns 2-letter ISO country code for Google Ads API.
        """
        if not area_location:
            logger.warning("No area_location provided, defaulting to IN")
            return "IN"

        if not self._google_maps_api_key:
            logger.warning("Missing GOOGLE_MAPS_API_KEY, defaulting to IN")
            return "IN"

        try:
            # URL encode the address
            encoded_address = urllib.parse.quote(area_location)
            url = f"{self.GEOCODING_API_URL}?address={encoded_address}&key={self._google_maps_api_key}"

            # Asynchronous request for country inference
            client = await self._get_client()
            response = await client.get(url)

            if response.status_code != 200:
                logger.warning(
                    f"Geocoding API error: {response.status_code}, defaulting to IN"
                )
                return "IN"

            data = response.json()

            if data.get("status") != "OK":
                logger.warning(
                    f"Geocoding failed for '{area_location}': {data.get('status')}, defaulting to IN"
                )
                return "IN"

            # Extract country code from address_components
            for result in data.get("results", []):
                for component in result.get("address_components", []):
                    if "country" in component.get("types", []):
                        country_code = component.get("short_name", "IN")
                        logger.info(
                            f"Inferred country '{country_code}' from area_location '{area_location}'"
                        )
                        return country_code

            logger.warning(
                f"No country found in geocoding result for '{area_location}', defaulting to IN"
            )
            return "IN"

        except Exception as e:
            logger.exception(
                f"Error inferring country code for '{area_location}': {e}, defaulting to IN"
            )
            return "IN"

    def _is_valid_coordinates(self, coordinates: Optional[Dict]) -> bool:
        """Validate coordinates dictionary."""
        return bool(coordinates and coordinates.get("lat") and coordinates.get("lng"))

    def _has_google_ads_credentials(self) -> bool:
        """Check if Google Ads credentials are available."""
        return bool(self._developer_token and self._access_token)

    def _get_google_ads_headers(self) -> Dict[str, str]:
        """Build headers for Google Ads API requests."""
        return {
            "Authorization": f"Bearer {self._access_token}",
            "developer-token": self._developer_token,
            "Content-Type": "application/json",
        }

    def _select_most_specific_tier(
        self, locations: List[TargetPlaceLocation]
    ) -> List[TargetPlaceLocation]:
        """
        Select only the most specific tier of locations to avoid redundancy.

        Hierarchy (most specific to broadest):
        - Tier 1: Postal Code, Neighborhood, Sub District
        - Tier 2: City, District, Department
        - Tier 3: State
        - Tier 4: Country (last resort fallback)
        """
        if not locations:
            return locations

        # Group by tier
        tier1 = [
            loc
            for loc in locations
            if loc.target_type in ["Postal Code", "Neighborhood", "Sub District"]
        ]
        tier2 = [
            loc
            for loc in locations
            if loc.target_type in ["City", "District", "Department"]
        ]
        tier3 = [loc for loc in locations if loc.target_type in ["State"]]
        tier4 = [loc for loc in locations if loc.target_type == "Country"]

        logger.info("Hierarchical tier breakdown:")
        logger.info(
            f"  Tier 1 (Most specific): {len(tier1)} locations - {[loc.name for loc in tier1]}"
        )
        logger.info(
            f"  Tier 2 (Medium): {len(tier2)} locations - {[loc.name for loc in tier2]}"
        )
        logger.info(
            f"  Tier 3 (Broad): {len(tier3)} locations - {[loc.name for loc in tier3]}"
        )
        logger.info(
            f"  Tier 4 (Very broad): {len(tier4)} locations - {[loc.name for loc in tier4]}"
        )

        # Select most specific tier available
        if tier1:
            logger.info(f"✅ Selected Tier 1 (most specific): {len(tier1)} locations")
            return tier1
        elif tier2:
            logger.info(
                f"✅ Selected Tier 2 (fallback to cities): {len(tier2)} locations"
            )
            return tier2
        elif tier3:
            logger.info(
                f"✅ Selected Tier 3 (fallback to state): {len(tier3)} locations"
            )
            return tier3
        elif tier4:
            logger.warning(
                f"⚠️ Selected Tier 4 (country - very broad, last resort): {len(tier4)} locations"
            )
            return tier4
        else:
            logger.error("No valid tier found, returning empty list")
            return []

    def _process_suggestions(
        self, suggestions: List[Dict], area_location: Optional[str]
    ) -> tuple[List[TargetPlaceLocation], set]:
        """Process geo target suggestions and filter by area."""
        resolved: List[TargetPlaceLocation] = []
        resolved_canonical_names: set = set()
        resolved_search_terms: set = set()
        area_lower = area_location.lower() if area_location else None

        logger.info(f"Processing {len(suggestions)} suggestions from Google Ads API:")

        for idx, suggestion in enumerate(suggestions, 1):
            geo_target = suggestion.get("geoTargetConstant", {})
            search_term = suggestion.get("searchTerm", "")
            canonical_name = geo_target.get("canonicalName", "")
            target_type = geo_target.get("targetType", "")
            resource_name = geo_target.get("resourceName", "")

            # Log each suggestion
            logger.info(
                f"  [{idx}] {search_term} → {canonical_name} (Type: {target_type})"
            )

            # Skip if no resource name
            if not resource_name:
                logger.info(f"❌ Skipped: No resourceName")
                continue

            # Skip duplicates (check canonical_name, not search_term)
            if canonical_name.lower() in resolved_canonical_names:
                logger.info(f"    ❌ Skipped: Duplicate canonical name")
                continue

            # Filter by area_location to prevent wrong state matches
            # e.g., "Sarjapur" should match Karnataka, not Bihar/Maharashtra
            # Note: Country is NOT filtered here - kept as Tier 4 fallback
            if (
                area_lower
                and target_type != "Country"
                and area_lower not in canonical_name.lower()
            ):
                logger.info(
                    f"    ❌ Skipped: Not in area '{area_location}' (found in {canonical_name})"
                )
                continue

            # Accept this target
            logger.info(f"    ✅ Accepted")
            resolved.append(
                TargetPlaceLocation(
                    name=search_term,
                    resource_name=resource_name,
                    canonical_name=canonical_name,
                    target_type=target_type,
                )
            )
            resolved_canonical_names.add(canonical_name.lower())
            resolved_search_terms.add(search_term.lower())

        return resolved, resolved_search_terms

    def _extract_locations_from_geocode(self, data: Dict) -> List[str]:
        """Extract location names from geocoding API response."""
        locations: List[str] = []

        for result in data.get("results", []):
            for component in result.get("address_components", []):
                types = component.get("types", [])
                name = component.get("long_name", "")

                if any(t in types for t in self.ADDRESS_TYPES):
                    if name and name not in locations:
                        locations.append(name)

        return locations

    def _extract_place_names(self, data: Dict) -> List[str]:
        """Extract place names from Places API response."""
        places: List[str] = []

        for result in data.get("results", []):
            name = result.get("name", "")
            if name and name not in places:
                places.append(name)

        return places
