from pydantic import BaseModel
from typing import Dict, Optional


class MetaAdSetRequest(BaseModel):
    dataObjectId: Optional[str] = None
    goal: Optional[str] = None
    region: Optional[str] = None

    adAccountId: Optional[str] = None
    campaignId: Optional[str] = None
    adsetPayload: Optional[Dict] = None
