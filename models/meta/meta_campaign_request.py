from pydantic import BaseModel
from typing import Dict, Optional

class MetaCampaignRequest(BaseModel):
    dataObjectId: Optional[str] = None
    businessName: Optional[str] = None
    goal: Optional[str] = None

    adAccountId: Optional[str] = None
    campaignPayload: Optional[Dict] = None
