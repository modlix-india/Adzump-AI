from typing import List, Optional
from pydantic import BaseModel


class MapRequest(BaseModel):
    places: List[str]


class GeoDiscoveryRequest(BaseModel):
    storage_id: Optional[str] = None
    business_url: Optional[str] = None
    coordinates: Optional[dict] = None
    area_location: Optional[str] = None
    radius_km: int = 15


class TargetPlaceLocation(BaseModel):
    name: str
    resource_name: str
    canonical_name: Optional[str] = None
    target_type: Optional[str] = None
    distance_km: Optional[float] = None  # Distance from center coordinates


class TargetPlaceResponse(BaseModel):
    locations: List[TargetPlaceLocation]
    unresolved: List[str] = []
    product_location: Optional[str] = None
    product_coordinates: Optional[dict] = None
