from pydantic import BaseModel, HttpUrl
from typing import Optional


class GenerateMetaCampaignRequest(BaseModel):
    dataObjectId: str
    businessName: str
    goal: str