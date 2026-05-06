import json
import os
from typing import List
from fastapi import APIRouter, HTTPException, Query, Header
from fastapi.responses import HTMLResponse

from services.maps.place_resolver import resolve_place_to_id
from models.maps_model import MapRequest, GeoDiscoveryRequest, TargetPlaceResponse
from services.geo_target_service import GeoTargetService
from oserver.services.storage_service import StorageService
from oserver.models.storage_request_model import (
    StorageReadRequest,
    StorageFilter,
    StorageUpdateWithPayload,
)

router = APIRouter(prefix="/api/ds/maps", tags=["Maps"])


@router.post("/render")
async def render_map_url(req: MapRequest):
    if not req.places:
        raise HTTPException(status_code=400, detail="No places provided")

    place_ids: List[str] = []

    for place in req.places:
        pid = await resolve_place_to_id(place)
        place_ids.append(pid)

    return {"iframe_url": f"/api/ds/maps/view?pids={','.join(place_ids)}"}


@router.post("/discover", response_model=TargetPlaceResponse)
async def discover_geo_targets(
    req: GeoDiscoveryRequest,
    client_code: str = Header(..., alias="clientCode"),
    authorization: str = Header(...),
    x_forwarded_host: str = Header(..., alias="x-forwarded-host"),
    x_forwarded_port: str = Header(..., alias="x-forwarded-port"),
):
    """
    Discovers geo-target constants around a center point and updates AISuggestedData storage.
    """
    # Extract token from authorization header (stripping Bearer if present)
    resolved_token = authorization
    if authorization.lower().startswith("bearer "):
        resolved_token = authorization[7:]

    if not resolved_token:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    storage_service = StorageService(
        access_token=resolved_token,
        client_code=client_code,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port,
    )
    geo_service = GeoTargetService(client_code=client_code)

    # 1. Identify the record in AISuggestedData
    storage_id = req.storage_id
    if not storage_id and req.business_url:
        read_req = StorageReadRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            clientCode=client_code,
            filter=StorageFilter(field="businessUrl", value=req.business_url),
        )
        existing_data = await storage_service.read_page_storage(read_req)
        if existing_data.success and existing_data.content:
            storage_id = existing_data.content[-1].get("_id")

    if not storage_id:
        raise HTTPException(
            status_code=400,
            detail="Could not find an existing record for the provided storage_id or business_url",
        )

    # 2. Perform Discovery
    try:
        geo_result = await geo_service.suggest_geo_targets(
            coordinates=req.coordinates,
            area_location=req.area_location,
            radius_km=req.radius_km,
        )

        # 3. Format and Update Storage
        suggested_geo_targets = [
            {
                "name": loc.name,
                "resourceName": loc.resource_name,
                "canonicalName": loc.canonical_name,
                "targetType": loc.target_type,
                "distance_km": loc.distance_km,
            }
            for loc in geo_result.locations
        ]

        update_payload = StorageUpdateWithPayload(
            storageName="AISuggestedData",
            clientCode=client_code,
            appCode="",
            dataObjectId=storage_id,
            dataObject={
                "location": {
                    "product_location": geo_result.product_location,
                    "product_coordinates": geo_result.product_coordinates,
                },
                "suggestedGeoTargets": suggested_geo_targets,
                "unresolvedGeoTargets": geo_result.unresolved,
            },
            isPartial=True,
        )

        await storage_service.update_storage(update_payload)

        # 4. Return result
        return geo_result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Discovery failed: {str(e)}")


@router.get("/view", response_class=HTMLResponse)
def render_map(pids: str = Query(...)):
    place_ids = pids.split(",")

    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Location Targeting Map</title>
  <style>
    html, body, #map {{
      height: 100%;
      margin: 0;
      padding: 0;
    }}
  </style>
</head>

<body>
<div id="map"></div>

<script>
  // These are FIXED for this page load
  const PLACE_IDS = new Set({json.dumps(place_ids)});
</script>

<script>
function initMap() {{
  const map = new google.maps.Map(document.getElementById("map"), {{
    center: {{ lat: 20.5937, lng: 78.9629 }},
    zoom: 5,
    mapId: "{os.getenv("GOOGLE_MAP_ID")}"
  }});

  const LAYERS = [
    "COUNTRY",
    "ADMINISTRATIVE_AREA_LEVEL_1",
    "ADMINISTRATIVE_AREA_LEVEL_2",
    "LOCALITY"
  ];

  map.addListener("idle", () => {{
    LAYERS.forEach(type => {{
      const layer = map.getFeatureLayer(type);
      if (!layer || !layer.isAvailable) return;

      layer.style = ({{ feature }}) => {{
        if (PLACE_IDS.has(feature.placeId)) {{
          return {{
            fillColor: "#4285F4",
            fillOpacity: 0.4,
            strokeColor: "#1a73e8",
            strokeWeight: 1
          }};
        }}
      }};
    }});
  }});
}}
</script>

<script
  src="https://maps.googleapis.com/maps/api/js?key={os.getenv("GOOGLE_MAPS_API_KEY")}&callback=initMap"
  async defer>
</script>

</body>
</html>
"""
