from pydantic import BaseModel, Field, field_validator

class BudgetRecommendationResponse(BaseModel):
    campaign_id: str
    suggested_amount: float = Field(..., description="Suggested daily budget in numeric format")
    rationale: str = Field(..., description="Reasoning behind budget suggestion")

    @field_validator("suggested_amount")
    def check_amount(cls, v):
        if v < 0:
            raise ValueError("Suggested amount cannot be negative")
        return v
