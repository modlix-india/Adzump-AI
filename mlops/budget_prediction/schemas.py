from typing import Optional, Literal
from pydantic import BaseModel, Field


class BudgetPredictionReq(BaseModel):
    clicks: int = Field(..., description="Projected total clicks")
    conversions: int = Field(..., description="Projected total conversions")
    duration_days: int = Field(..., description="Campaign duration in days")
    buffer_percent: float = Field(
        0.20, description="Buffer percentage to add to prediction (default 20%)"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "clicks": 500,
                "conversions": 10,
                "duration_days": 30,
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
    currency: str = Field("INR", description="Currency code")

    model_config = {
        "json_schema_extra": {
            "example": {
                "suggested_budget": 12000,
                "base_cost_prediction": 10000,
                "currency": "INR",
            }
        }
    }


class BudgetAPIResponse(BaseModel):
    status: Literal["success", "error"] = Field(..., description="Response status")
    data: Optional[BudgetPredictionData] = Field(
        None, description="Prediction data if success"
    )
    error: Optional[str] = Field(None, description="Error message if failed")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "success",
                "data": {
                    "suggested_budget": 12000,
                    "base_cost_prediction": 10000,
                    "currency": "INR",
                },
                "error": None,
            }
        }
    }
