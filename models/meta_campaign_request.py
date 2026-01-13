from pydantic import BaseModel, HttpUrl
from typing import Optional


class GenerateMetaCampaignRequest(BaseModel):
    businessName: str
    websiteURL: HttpUrl
    budget: float
    durationDays: int
    goal: str

