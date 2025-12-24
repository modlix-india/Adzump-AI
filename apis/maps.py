import json
import os
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List

from services.maps.place_resolver import resolve_place_to_id

router = APIRouter(prefix="/api/ds/maps", tags=["Maps"])


class MapRequest(BaseModel):
    places: List[str]


@router.post("/render")
async def render_map_url(req: MapRequest):
    if not req.places:
        raise HTTPException(status_code=400, detail="No places provided")

    place_ids: List[str] = []

    for place in req.places:
        pid = await resolve_place_to_id(place)
        place_ids.append(pid)

    return {
        "iframe_url": f"/api/ds/maps/view?pids={','.join(place_ids)}"
    }


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
