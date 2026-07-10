from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class GenerateCampaignRequest(BaseModel):
    customerId: str
    loginCustomerId: str
    businessName: str
    budget: float
    startDate: str
    endDate: str
    goal: str
    websiteURL: str
    geoTargetTypeSetting: Dict[str, Any]
    # Legacy geo input; optional now that curated locations are preferred
    locations: List[Dict[str, Any]] = []
    # Adzump user-curated locations; preferred over `locations` when present
    googleMappedLocations: Optional[List[Dict[str, Any]]] = None
    targeting: List[Dict[str, Any]]
    networkSettings: Optional[Dict[str, Any]] = None
    trackingUrlTemplate: Optional[str] = None
    finalUrlSuffix: Optional[str] = None
    # Assets optional, we will handle inside service if provided
    assets: Dict[str, Any] = None
