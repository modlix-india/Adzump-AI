import json
import structlog
from typing import Dict, Any, List

from adapters.meta.client import meta_client

logger = structlog.get_logger()

# Unknown types (e.g. subcity) coerced to city rather than dropped.
_CURATED_GEO_TYPES = {"country", "city", "region", "zip", "neighborhood"}


def curated_meta_locations(campaign_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Lift campaign_data["metaMappedLocations"] nested handles into build_geo_structure-ready dicts."""
    curated: List[Dict[str, Any]] = []
    for entry in campaign_data.get("metaMappedLocations") or []:
        handle = (entry or {}).get("meta") or {}
        key = handle.get("key")
        if not key:
            continue
        loc_type = (handle.get("type") or "").strip().lower()
        if loc_type not in _CURATED_GEO_TYPES:
            logger.warning(
                "meta_adset_geo.curated_type_coerced", key=key, type=loc_type,
            )
            loc_type = "city"
        curated.append({
            "key": str(key),
            "name": handle.get("name") or entry.get("name") or "",
            "type": loc_type,
        })
    return curated


class MetaGeoTargetingAdapter:

    async def search_locations(
        self,
        client_code: str,
        location_name: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search Meta ad geolocations using /search endpoint.
        """

        response = await meta_client.get(
            "/search",
            client_code=client_code,
            params={
                "type": "adgeolocation",
                "location_types": json.dumps(
                    ["neighborhood", "city", "zip", "region", "country"]
                ),
                "q": location_name,
                "limit": limit,
            },
        )

        data = response.get("data", [])

        if not data:
            logger.warning(
                "No Meta geo location found",
                location=location_name,
            )
            return []

        return data

    def build_geo_structure(
        self,
        meta_locations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:

        return {
                "data": [
                    {
                        "key": item.get("key"),
                        "name": item.get("name"),
                        "type": item.get("type"),
                        "country_code": item.get("country_code"),
                        "country_name": item.get("country_name"),
                        "region": item.get("region"),
                        "region_id": item.get("region_id"),
                        "geo_hierarchy_level": item.get("geo_hierarchy_level"),
                        "geo_hierarchy_name": item.get("geo_hierarchy_name"),
                        "supports_city": item.get("supports_city"),
                        "supports_region": item.get("supports_region"),
                    }
                    for item in meta_locations
                    if item.get("key")
                ]
        }