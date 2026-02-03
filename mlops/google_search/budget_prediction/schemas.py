from typing import Optional
from pydantic import BaseModel, Field


class BudgetPredictionReq(BaseModel):
    conversions: int = Field(..., description="Projected total conversions")
    duration_days: int = Field(..., description="Campaign duration in days")
    expected_conversion_rate: float = Field(
        12.0, description="Expected conversion rate in percentage (default 12%)"
    )
    buffer_percent: float = Field(
        0.20, description="Buffer percentage to add to prediction (default 20%)"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "conversions": 10,
                "duration_days": 30,
                "expected_conversion_rate": 12.0,
                "buffer_percent": 0.20,
            }
        }
    }


class BudgetPredictionData(BaseModel):
    suggested_budget: int = Field(
        ..., description="Recommended budget including buffer"
    )
    base_cost_prediction: int = Field(
        ..., description="Raw cost prediction before buffer"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "suggested_budget": 12000,
                "base_cost_prediction": 10000,
            }
        }
    }


class BudgetAPIResponse(BaseModel):
    success: bool = Field(True, description="Response status indicator")
    data: Optional[BudgetPredictionData] = Field(
        None, description="Prediction data if success"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "data": {
                    "suggested_budget": 12000,
                    "base_cost_prediction": 10000,
                },
            }
        }
    }
