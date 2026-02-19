import json
import structlog
from typing import Optional, Dict, Any, List

from adapters.meta.client import MetaClient
from exceptions.custom_exceptions import InternalServerException

logger = structlog.get_logger()


class MetaGeoTargetingAdapter:

    def __init__(self):
        self.client = MetaClient()

    async def search_locations(
        self,
        client_code: str,
        location_name: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:

        try:
            response = await self.client.get(
                client_code=client_code,
                endpoint="/search",
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

        except Exception as e:
            logger.error(
                "Meta geo location search failed",
                error=str(e),
                location=location_name,
            )
            raise InternalServerException("Failed to search Meta location")

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

            if meta_field not in geo_payload:
                geo_payload[meta_field] = []

            geo_payload[meta_field].append({"key": key})

        if not geo_payload:
            raise InternalServerException("No valid geo locations to build")

        return geo_payload