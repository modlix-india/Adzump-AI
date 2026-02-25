import json
import structlog
from typing import Dict, Any, List

from adapters.meta.client import meta_client

logger = structlog.get_logger()


class MetaGeoTargetingAdapter:

    async def search_locations(
        self,
        client_code: str,
        location_name: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:

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

        type_map = {
            "neighborhood": "neighborhoods",
            "city": "cities",
            "zip": "zips",
            "region": "regions",
            "country": "countries",
        }

        geo_payload: Dict[str, List[Dict[str, str]]] = {}

        for item in meta_locations:
            geo_type = item.get("type")
            key = item.get("key")

            if not geo_type or not key:
                continue

            meta_field = type_map.get(geo_type)
            if not meta_field:
                continue

            geo_payload.setdefault(meta_field, []).append({"key": key})

        return geo_payload