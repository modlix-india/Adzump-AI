from typing import List, Optional
from pydantic import BaseModel


class GeoTargetRequest(BaseModel):
    locations: List[str]
    parent_location: Optional[str] = None


class GeoTargetLocation(BaseModel):
    name: str                           
    resource_name: str                  
    canonical_name: Optional[str] = None 
    target_type: Optional[str] = None   


class GeoTargetResponse(BaseModel):
    locations: List[GeoTargetLocation]
    unresolved: List[str] = []
