import httpx
import os
from fastapi import HTTPException

PLACES_ENDPOINT = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"


async def resolve_place_to_id(place: str) -> str:
    if place.startswith("ChI"):
        return place

    params = {
        "input": place,
        "inputtype": "textquery",
        "fields": "place_id",
        "key": os.getenv("GOOGLE_MAPS_API_KEY"),
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(PLACES_ENDPOINT, params=params)
        data = resp.json()

    if data.get("status") != "OK" or not data.get("candidates"):
        raise HTTPException(
            status_code=400,
            detail=f"Unable to resolve placeId for '{place}'"
        )

    return data["candidates"][0]["place_id"]
