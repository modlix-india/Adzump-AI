import os
import httpx
from typing import List
from structlog import get_logger  # type: ignore
from models.geo_target_model import GeoTargetLocation, GeoTargetResponse

logger = get_logger(__name__)


class GeoTargetService:

    GOOGLE_ADS_API_VERSION = "v20"
    SUGGEST_ENDPOINT = f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}/geoTargetConstants:suggest"
    HTTP_TIMEOUT = 30.0

    async def resolve_locations_batch(
        self,
        locations: List[str],
        country_code: str = "IN",
        locale: str = "en",
        parent_location: str = None,
    ) -> GeoTargetResponse:
        developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
        access_token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN")

        if not developer_token or not access_token:
            logger.error("Missing Google Ads credentials")
            return GeoTargetResponse(locations=[], unresolved=locations)

        headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": developer_token,
            "Content-Type": "application/json",
        }

        payload = {
            "locale": locale,
            "countryCode": country_code,
            "locationNames": {"names": locations},
        }

        resolved: List[GeoTargetLocation] = []
        resolved_names: set = set()

        try:
            async with httpx.AsyncClient(timeout=self.HTTP_TIMEOUT) as client:
                response = await client.post(
                    self.SUGGEST_ENDPOINT, headers=headers, json=payload
                )

                if response.status_code != 200:
                    logger.error(f"Batch API error: {response.status_code}")
                    return GeoTargetResponse(locations=[], unresolved=locations)

                data = response.json()
                suggestions = data.get("geoTargetConstantSuggestions", [])
                parent_lower = parent_location.lower() if parent_location else None

                for suggestion in suggestions:
                    geo_target = suggestion.get("geoTargetConstant", {})
                    search_term = suggestion.get("searchTerm", "")
                    canonical_name = geo_target.get("canonicalName", "")

                    if search_term.lower() in resolved_names:
                        continue

                    if parent_lower and parent_lower not in canonical_name.lower():
                        continue

                    if geo_target.get("resourceName"):
                        resolved.append(
                            GeoTargetLocation(
                                name=search_term,
                                resource_name=geo_target.get("resourceName", ""),
                                canonical_name=canonical_name,
                                target_type=geo_target.get("targetType"),
                            )
                        )
                        resolved_names.add(search_term.lower())

        except Exception as e:
            logger.exception(f"Batch resolution failed: {e}")
            return GeoTargetResponse(locations=[], unresolved=locations)

        unresolved = [loc for loc in locations if loc.lower() not in resolved_names]

        logger.info(f"Resolved {len(resolved)} locations, {len(unresolved)} unresolved")
        return GeoTargetResponse(locations=resolved, unresolved=unresolved)
