from typing import List, Literal
from pydantic import BaseModel, Field, ConfigDict


from models.keyword_model import KeywordInput


class PerformancePredictionReq(BaseModel):
    """Request body for ad performance prediction."""

    keyword_data: List[KeywordInput] = Field(
        ..., min_length=1, description="List of keywords with their match types"
    )
    total_budget: float = Field(
        ..., gt=0, description="Total campaign budget to distribute among keywords"
    )
    bid_strategy: str = Field(
        ...,
        min_length=1,
        description="Bid strategy type, e.g., 'Maximize Conversions', 'Maximize Clicks'",
    )
    period: Literal["Weekly", "Monthly"] = Field(
        default="Monthly", description="Prediction timeframe"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "keyword_data": [
                    {"keyword": "luxury villas bangalore", "match_type": "Exact match"},
                    {"keyword": "3bhk apartments north", "match_type": "Phrase match"},
                    {"keyword": "buy house near me", "match_type": "Broad match"},
                ],
                "total_budget": 50000,
                "bid_strategy": "Maximize Conversions",
                "period": "Monthly",
            }
        }
    )


class PerformancePredictionData(BaseModel):
    """Response body with predicted performance ranges."""

    timeframe: str = Field(..., description="Prediction period (Weekly/Monthly)")
    budget_allocated: str = Field(..., description="Formatted budget amount")
    impressions: str = Field(..., description="Predicted impressions range")
    clicks: str = Field(..., description="Predicted clicks range")
    conversions: str = Field(..., description="Predicted conversions range")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "timeframe": "Monthly",
                "budget_allocated": "₹50,000",
                "impressions": "10,000 - 25,000",
                "clicks": "500 - 1,200",
                "conversions": "20 - 50",
            }
        }
    )
