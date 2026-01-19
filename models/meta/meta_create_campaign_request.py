from pydantic import BaseModel
from typing import Dict

class CreateMetaCampaignRequest(BaseModel):
    adAccountId: str
    campaignPayload: Dict
