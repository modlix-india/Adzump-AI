from pydantic import BaseModel, Field, field_validator

# ---------------------- Recommended Budget Schema ----------------------
class RecommendedBudget(BaseModel):
    suggested_amount: float = Field(..., description="Suggested daily budget in numeric format")
    rationale: str = Field(..., description="Reasoning behind budget suggestion")

    @field_validator("suggested_amount")
    def check_amount(cls, v):
        if v < 0:
            raise ValueError("Suggested amount cannot be negative")
        return v


# ---------------------- Final Response Schema ----------------------
class BudgetRecommendationResponse(BaseModel):
    campaign_id: str
    recommended_budget: RecommendedBudget