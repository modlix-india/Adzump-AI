from typing import List, Literal, Optional
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
    """Response body with predicted performance estimates."""

    timeframe: str = Field(..., description="Prediction period (Weekly/Monthly)")
    budget_allocated: str = Field(..., description="Formatted budget amount")
    impressions: str = Field(..., description="Predicted total impressions")
    clicks: str = Field(..., description="Predicted total clicks")
    conversions: str = Field(..., description="Predicted total conversions")
    ctr: str = Field(..., description="Predicted Click-Through Rate (%)")
    cpa: str = Field(..., description="Predicted Cost Per Conversion")
    conversion_rate: str = Field(..., description="Predicted Conversion Rate (%)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "timeframe": "Monthly",
                "budget_allocated": "₹15,000",
                "impressions": "1,333",
                "clicks": "211",
                "conversions": "11",
                "ctr": "15.83%",
                "cpa": "₹1,363",
                "conversion_rate": "5.21%",
            }
        }
    )


class PerformanceAPIResponse(BaseModel):
    status: Literal["success", "error"] = Field(..., description="Response status")
    data: Optional[PerformancePredictionData] = Field(
        None, description="Prediction data if success"
    )
    error: Optional[str] = Field(None, description="Error message if failed")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "success",
                "data": {
                    "timeframe": "Monthly",
                    "budget_allocated": "₹15,000",
                    "impressions": "1,333",
                    "clicks": "211",
                    "conversions": "11",
                    "ctr": "15.83%",
                    "cpa": "₹1,363",
                    "conversion_rate": "5.21%",
                },
                "error": None,
            }
        }
    )
