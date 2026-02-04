import os
import httpx
import math
import asyncio
import urllib.parse
from math import radians, sin, cos, sqrt, atan2
from asyncio import Semaphore
from typing import List, Dict, Optional
from structlog import get_logger  # type: ignore
from models.maps_model import TargetPlaceLocation, TargetPlaceResponse
from oserver.services.connection import fetch_google_api_token_simple

logger = get_logger(__name__)


class GeoTargetService:
    GOOGLE_ADS_API_VERSION = "v20"
    SUGGEST_ENDPOINT = f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}/geoTargetConstants:suggest"
    GEOCODING_API_URL = "https://maps.googleapis.com/maps/api/geocode/json"
    HTTP_TIMEOUT = 30.0
    DEFAULT_RADIUS_KM = 15

    # Grid configuration
    GRID_STEP_KM = 5  # 5km steps
    MAX_GRID_POINTS = 40  # Safety cap
    MAX_CONCURRENT_GEOCODE = 10  # Parallel requests
    MIN_DISTANCE_KM = 2.0  # Deduplication threshold

    def __init__(self, client_code: str):
        self._google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        self._developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
        self._access_token = fetch_google_api_token_simple(client_code)
        # self._access_token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN")

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

    async def suggest_geo_targets(
        self,
        coordinates: Optional[Dict[str, float]] = None,
        area_location: Optional[str] = None,
        radius_km: int = DEFAULT_RADIUS_KM,
    ) -> TargetPlaceResponse:
        product_location = area_location
        product_coordinates = coordinates

        # Try to get coordinates - either from input or by geocoding area_location
        if not self._is_valid_coordinates(coordinates):
            if area_location:
                logger.info(
                    f"No coordinates - geocoding area_location: {area_location}"
                )
                geo_data = await self._geocode_area_location(area_location)
                if geo_data:
                    coordinates = {"lat": geo_data["lat"], "lng": geo_data["lng"]}
                    product_location = geo_data.get("name", area_location)
                    product_coordinates = coordinates

            if not self._is_valid_coordinates(coordinates):
                logger.error("No valid coordinates and no area_location to geocode")
                return TargetPlaceResponse(locations=[], unresolved=[])

        # If coordinates were provided directly (map embed), reverse-geocode to get the specific business site name
        if self._is_valid_coordinates(product_coordinates):
            rev_geo = await self._reverse_geocode_center(
                product_coordinates["lat"], product_coordinates["lng"]
            )
            if rev_geo:
                product_location = rev_geo

        lat, lng = coordinates["lat"], coordinates["lng"]
        logger.info(
            f"Starting grid-based geo-targeting at ({lat}, {lng}), radius={radius_km}km"
        )

        # Step 1: Generate grid
        grid_points = self._generate_grid_points(
            lat, lng, radius_km, step_km=self.GRID_STEP_KM
        )

        # Step 2: Geocode grid points (async) + extract country
        locations, country_code = await self._geocode_grid_points_async(grid_points)

        if not locations:
            logger.warning("No locations found from grid")
            return TargetPlaceResponse(locations=[], unresolved=[])

        # Step 3: Spatial Deduplication (prune redundant nearby neighbors)
        locations = self._deduplicate_locations(locations)

        # Step 4: Verify location centers and filter by actual distance
        # We uniquely identify locations and geocode them to get their true centers
        verified_locations = await self._verify_location_centers_async(
            locations=locations, center_lat=lat, center_lng=lng, radius_km=radius_km
        )

        if not verified_locations:
            logger.warning("No locations within radius after center verification")
            return TargetPlaceResponse(
                locations=[], unresolved=[loc["name"] for loc in locations]
            )

        # Step 4: Extract names for Google Ads resolution
        location_names = [loc["name"] for loc in verified_locations]

        logger.info(
            f"Resolving {len(location_names)} verified locations to geo-target constants"
        )

        # Step 5: Resolve to Google Ads (using extracted country_code)
        result = await self.resolve_locations_batch(
            locations=location_names,
            country_code=country_code,
        )

        # Add distance and LOG distances after resolution
        distance_map = {
            loc["name"]: loc.get("distance_km") for loc in verified_locations
        }

        logger.info("--- FINAL DISTANCE VALIDATION (AFTER RESOLUTION) ---")
        for resolved_loc in result.locations:
            dist = distance_map.get(resolved_loc.name)
            resolved_loc.distance_km = dist
            logger.info(
                f"📍 {resolved_loc.name} -> {resolved_loc.canonical_name}: {dist}km"
            )

        logger.info(f"Final Result: {len(result.locations)} geo-targets")
        result.product_location = product_location
        result.product_coordinates = product_coordinates
        return result

    def _generate_grid_points(
        self, center_lat: float, center_lng: float, radius_km: int, step_km: int = 5
    ) -> List[Dict[str, float]]:
        """Generate grid points within circular radius."""
        points = []
        km_per_deg_lat = 111.0
        km_per_deg_lng = 111.0 * math.cos(math.radians(center_lat))

        d_lat = -radius_km
        while d_lat <= radius_km:
            d_lng = -radius_km
            while d_lng <= radius_km:
                distance = math.sqrt(d_lat**2 + d_lng**2)

                if distance <= radius_km:
                    points.append(
                        {
                            "lat": center_lat + (d_lat / km_per_deg_lat),
                            "lng": center_lng + (d_lng / km_per_deg_lng),
                        }
                    )

                d_lng += step_km
            d_lat += step_km

        if len(points) > self.MAX_GRID_POINTS:
            points = points[: self.MAX_GRID_POINTS]

        logger.info(f"Generated {len(points)} grid points")
        return points

    async def _geocode_grid_points_async(
        self, points: List[Dict[str, float]]
    ) -> tuple[List[Dict], str]:
        country_code: Optional[str] = None
        semaphore = Semaphore(self.MAX_CONCURRENT_GEOCODE)

        async def geocode_one(point: Dict) -> Optional[Dict]:
            nonlocal country_code
            async with semaphore:
                await asyncio.sleep(0.05)  # Rate limiting

                try:
                    client = await self._get_client()
                    url = (
                        f"{self.GEOCODING_API_URL}?"
                        f"latlng={point['lat']},{point['lng']}&"
                        f"key={self._google_maps_api_key}"
                    )

                    response = await client.get(url, timeout=10.0)

                    if response.status_code != 200:
                        return None

                    data = response.json()

                    if data.get("status") != "OK":
                        return None

                    results = data.get("results", [])
                    if not results:
                        return None

                    if not country_code:
                        for component in results[0].get("address_components", []):
                            types = component.get("types", [])
                            if "country" in types:
                                country_code = component.get("short_name", "IN")

                    # Define target types in priority order
                    target_types = [
                        "sublocality_level_1",
                        "sublocality",
                        "neighborhood",
                        "locality",
                    ]

                    # Find the best locality/neighborhood and also a parent city
                    best_component = None
                    parent_city = ""
                    best_res = None

                    for res in results:
                        for component in res.get("address_components", []):
                            comp_types = component.get("types", [])

                            # Check if this could be our target
                            if not best_component:
                                matched_type = next(
                                    (t for t in target_types if t in comp_types), None
                                )
                                if matched_type:
                                    best_component = component
                                    best_component["matched_type"] = matched_type
                                    best_res = res

                            # Check if this is a good parent city (Locality/Admin Area 2)
                            if not parent_city:
                                if (
                                    "locality" in comp_types
                                    or "administrative_area_level_2" in comp_types
                                ):
                                    parent_city = component.get("long_name", "")

                    if best_component and best_res:
                        name = best_component.get("long_name")
                        # Add parent city if it's different from the name itself
                        search_name = name
                        if parent_city and parent_city.lower() != name.lower():
                            search_name = f"{name}, {parent_city}"

                        geo = best_res.get("geometry", {}).get("location", {})
                        return {
                            "name": search_name,
                            "lat": geo.get("lat", point["lat"]),
                            "lng": geo.get("lng", point["lng"]),
                            "type": best_component["matched_type"],
                        }

                    return None

                except Exception as e:
                    logger.debug(f"Geocoding failed: {e}")
                    return None

        tasks = [geocode_one(p) for p in points]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        locations = [r for r in results if r and isinstance(r, dict)]

        if not country_code:
            country_code = "IN"
            logger.warning("No country code found in grid results, defaulting to IN")

        logger.info(
            f"Found {len(locations)} locations from grid, country: {country_code}"
        )
        return locations, country_code

    def _deduplicate_locations(self, locations: List[Dict]) -> List[Dict]:
        """Deduplicate by name and distance."""
        unique = []

        for new_loc in locations:
            is_duplicate = False

            for existing in unique:
                # Same name (case-insensitive)
                if new_loc["name"].lower() == existing["name"].lower():
                    is_duplicate = True
                    break

                # Too close geographically
                distance = self._calculate_distance_km(
                    (new_loc["lat"], new_loc["lng"]), (existing["lat"], existing["lng"])
                )

                if distance < self.MIN_DISTANCE_KM:
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique.append(new_loc)

        logger.info(f"Deduplicated: {len(locations)} → {len(unique)}")
        return unique

    async def resolve_locations_batch(
        self,
        locations: List[str],
        country_code: str = "IN",
        locale: str = "en",
    ) -> TargetPlaceResponse:
        """Resolve location names to geoTargetConstants using Google Ads API."""
        if not self._has_google_ads_credentials():
            logger.error("Missing Google Ads credentials")
            return TargetPlaceResponse(locations=[], unresolved=locations)

        logger.info(
            f"Resolving {len(locations)} locations with country_code: {country_code}"
        )

        # Google Ads API limit: max 25 location names per request
        BATCH_SIZE = 25
        all_resolved: List[TargetPlaceLocation] = []
        all_resolved_names: set = set()

        # Split locations into batches
        for i in range(0, len(locations), BATCH_SIZE):
            batch = locations[i : i + BATCH_SIZE]
            logger.info(
                f"Processing batch {i // BATCH_SIZE + 1}: {len(batch)} locations"
            )

            headers = self._get_google_ads_headers()
            payload = {
                "locale": locale,
                "countryCode": country_code,
                "locationNames": {"names": batch},
            }

            try:
                client = await self._get_client()
                response = await client.post(
                    self.SUGGEST_ENDPOINT, headers=headers, json=payload
                )

                if response.status_code != 200:
                    logger.error(
                        f"Google Ads API error for batch: {response.status_code} - {response.text}"
                    )
                    continue  # Skip this batch and continue with others

                data = response.json()
                suggestions = data.get("geoTargetConstantSuggestions", [])
                logger.info(
                    f"Google Ads API returned {len(suggestions)} suggestions for {len(batch)} locations in this batch"
                )

                # Pass original batch locations to filter unrelated suggestions
                resolved, resolved_names = self._process_suggestions(
                    suggestions,
                    original_locations=set(loc.lower() for loc in batch),
                )

                # Accumulate results
                all_resolved.extend(resolved)
                all_resolved_names.update(resolved_names)

            except Exception as e:
                logger.exception(
                    f"Batch resolution failed for batch {i // BATCH_SIZE + 1}: {e}"
                )
                continue  # Skip this batch and continue with others

        unresolved = [loc for loc in locations if loc.lower() not in all_resolved_names]

        logger.info(
            f"Resolved {len(all_resolved)} locations, {len(unresolved)} unresolved"
        )
        return TargetPlaceResponse(locations=all_resolved, unresolved=unresolved)

    def _calculate_distance_km(
        self, coords1: tuple[float, float], coords2: tuple[float, float]
    ) -> float:
        lat1, lon1 = coords1
        lat2, lon2 = coords2

        # Earth's radius in kilometers
        R = 6371.0

        # Convert to radians
        lat1_rad = radians(lat1)
        lat2_rad = radians(lat2)
        delta_lat = radians(lat2 - lat1)
        delta_lon = radians(lon2 - lon1)

        # Haversine formula
        a = (
            sin(delta_lat / 2) ** 2
            + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
        )
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        distance = R * c

        return round(distance, 2)

    def _is_valid_coordinates(self, coordinates: Optional[Dict]) -> bool:
        return bool(coordinates and coordinates.get("lat") and coordinates.get("lng"))

    async def _geocode_area_location(
        self, area_location: str
    ) -> Optional[Dict[str, float]]:
        if not self._google_maps_api_key:
            logger.warning("Missing GOOGLE_MAPS_API_KEY for geocoding")
            return None

        try:
            encoded_address = urllib.parse.quote(area_location)
            url = f"{self.GEOCODING_API_URL}?address={encoded_address}&key={self._google_maps_api_key}"

            client = await self._get_client()
            response = await client.get(url, timeout=10.0)

            if response.status_code != 200:
                logger.warning(f"Geocoding API error: {response.status_code}")
                return None

            data = response.json()

            if data.get("status") != "OK":
                logger.warning(
                    f"Geocoding failed for '{area_location}': {data.get('status')}"
                )
                return None

            # Extract coordinates from first result
            results = data.get("results", [])
            if results:
                location = results[0].get("geometry", {}).get("location", {})
                lat = location.get("lat")
                lng = location.get("lng")
                formatted_address = results[0].get("formatted_address")

                if lat and lng:
                    logger.info(f"Geocoded '{area_location}' to ({lat}, {lng})")
                    return {"lat": lat, "lng": lng, "name": formatted_address}

            logger.warning(f"No coordinates found for '{area_location}'")
            return None

        except Exception as e:
            logger.exception(f"Error geocoding '{area_location}': {e}")
            return None

    async def _reverse_geocode_center(self, lat: float, lng: float) -> Optional[str]:
        """Reverse geocode specific coordinates to get a formal address name."""
        if not self._google_maps_api_key:
            return None

        try:
            url = f"{self.GEOCODING_API_URL}?latlng={lat},{lng}&key={self._google_maps_api_key}"
            client = await self._get_client()
            response = await client.get(url, timeout=10.0)
            data = response.json()

            if data.get("status") == "OK" and data.get("results"):
                # Use formatted address of the most specific result
                return data["results"][0].get("formatted_address")
        except Exception as e:
            logger.debug(f"Reverse geocoding center failed: {e}")
        return None

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

    async def _verify_location_centers_async(
        self,
        locations: List[Dict],
        center_lat: float,
        center_lng: float,
        radius_km: float,
    ) -> List[Dict]:
        # Unique names only to avoid redundant geocoding
        unique_locations = {}
        for loc in locations:
            name = loc["name"]
            if name not in unique_locations:
                unique_locations[name] = loc

        logger.info(f"Verifying centers for {len(unique_locations)} unique localities")

        verified = []
        semaphore = Semaphore(self.MAX_CONCURRENT_GEOCODE)

        async def verify_one(name: str):
            async with semaphore:
                try:
                    client = await self._get_client()
                    params = {
                        "address": name,
                        "key": self._google_maps_api_key,
                    }
                    response = await client.get(self.GEOCODING_API_URL, params=params)
                    data = response.json()

                    if data.get("status") == "OK" and data.get("results"):
                        result = data["results"][0]
                        geo = result.get("geometry", {}).get("location", {})
                        official_lat = geo.get("lat")
                        official_lng = geo.get("lng")

                        dist = self._calculate_distance_km(
                            (center_lat, center_lng), (official_lat, official_lng)
                        )

                        if dist <= radius_km:
                            logger.info(
                                f"STAGE 1 (PRE): {name} -> {dist:.2f}km (ACCEPTED)"
                            )
                            return {
                                "name": name,
                                "lat": official_lat,
                                "lng": official_lng,
                                "distance_km": dist,
                            }
                        else:
                            logger.info(
                                f"STAGE 1 (PRE): {name} -> {dist:.2f}km (DISCARDED: TOO FAR)"
                            )
                    else:
                        # If geocoding fails, fallback to original grid point distance (optimistic)
                        # but usually we want to be strict here
                        logger.debug(
                            f"Could not forward-geocode '{name}' for center verification"
                        )
                except Exception as e:
                    logger.error(f"Error verifying center for {name}: {e}")
            return None

        # Run verification in parallel
        tasks = [verify_one(name) for name in unique_locations.keys()]
        results = await asyncio.gather(*tasks)

        verified = [r for r in results if r is not None]
        logger.info(
            f"Verified {len(verified)} locations are truly within {radius_km}km"
        )
        return verified

    def _process_suggestions(
        self,
        suggestions: List[Dict],
        original_locations: set = None,
    ) -> tuple[List[TargetPlaceLocation], set]:
        resolved: List[TargetPlaceLocation] = []
        resolved_canonical_names: set = set()
        resolved_search_terms: set = set()
        original_locations = original_locations or set()

        # Group suggestions by search term to pick best match per term
        by_search_term: Dict[str, List[Dict]] = {}

        for suggestion in suggestions:
            geo_target = suggestion.get("geoTargetConstant", {})
            search_term = suggestion.get("searchTerm", "") or ""
            canonical_name = geo_target.get("canonicalName", "")
            target_type = geo_target.get("targetType", "")
            resource_name = geo_target.get("resourceName", "")

            if not resource_name or not search_term:
                continue

            search_term_lower = search_term.lower()
            if original_locations and search_term_lower not in original_locations:
                continue
            search_specific = search_term.split(",")[0].strip().lower()
            result_specific = canonical_name.split(",")[0].strip().lower()

            if target_type == "Postal Code":
                pass  # Postal codes are usually exact
            elif search_specific != result_specific:
                logger.debug(
                    f"Skipping broad/parent match: {canonical_name} for specific search: {search_term}"
                )
                continue

            if target_type in ["City", "Sub District", "District", "Country", "State"]:
                logger.debug(
                    f"Skipping broad regional target: {canonical_name} ({target_type})"
                )
                continue

            # Removed state filtering to support multi-state radius results
            # The Haversine distance verification in Step 3 is now our primary accuracy anchor.

            if search_term_lower not in by_search_term:
                by_search_term[search_term_lower] = []

            by_search_term[search_term_lower].append(
                {
                    "canonical_name": canonical_name,
                    "target_type": target_type,
                    "resource_name": resource_name,
                    "search_term": search_term,
                }
            )

        # Pick best match per term
        for term_lower, matches in by_search_term.items():
            # Priority: Neighborhood > Sublocality > Postal Code
            score_map = {
                "Neighborhood": 1,
                "Sublocality": 2,
                "Postal Code": 3,
            }

            matches.sort(key=lambda x: score_map.get(x["target_type"], 10))

            for match in matches:
                canon_lower = match["canonical_name"].lower()
                if canon_lower not in resolved_canonical_names:
                    # Keep original search term for mapping back to distance

                    resolved.append(
                        TargetPlaceLocation(
                            name=match[
                                "search_term"
                            ],  # Use search term for distance mapping
                            resource_name=match["resource_name"],
                            canonical_name=match["canonical_name"],
                            target_type=match["target_type"],
                        )
                    )
                    resolved_canonical_names.add(canon_lower)
                    resolved_search_terms.add(term_lower)
                    logger.info(
                        f"{match['search_term']} \u2192 {match['canonical_name']} ({match['target_type']})"
                    )
                    break

        return resolved, resolved_search_terms
