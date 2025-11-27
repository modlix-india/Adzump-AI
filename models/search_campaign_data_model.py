from typing import List,Dict,Any,Optional
from pydantic import BaseModel

class GenerateCampaignRequest(BaseModel):
    customer_id: str
    loginCustomerId: str
    businessName: str
    budget: float
    startDate: str
    endDate: str
    goal: str
    websiteURL: str
    geoTargetTypeSetting: Dict[str, Any]
    locations: List[Dict[str, str]]
    targeting: List[Dict[str, Any]]
    networkSettings: Optional[Dict[str, Any]] = None
    # Assets optional, we will handle inside service if provided
    assets: Dict[str, Any] = None