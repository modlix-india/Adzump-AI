from pydantic import BaseModel
from typing import List, Optional

class OptimizedAgeGroup(BaseModel):
    age_range: str
    reason: Optional[str]

class AgeOptimizationResponse(BaseModel):
    campaign_id: str
    optimized_age_groups: List[OptimizedAgeGroup]
    rationale: str
