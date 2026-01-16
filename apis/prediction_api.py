"""
Prediction API Router

FastAPI router for ad performance prediction endpoints.
"""

import os
import structlog
from fastapi import APIRouter, HTTPException
from mlops.prediction_schemas import PredictionRequest, PredictionResponse
from mlops.ad_performance_predictor import AdPerformancePredictor

# Configure logger
logger = structlog.get_logger()

router = APIRouter(prefix="/api/ds/prediction", tags=["prediction"])

# Initialize the predictor with configurable model directory
# Default path - update this to your actual model directory
MODEL_DIR = os.getenv("AD_PREDICTOR_MODEL_DIR", "mlops/models")

predictor = AdPerformancePredictor(model_dir=MODEL_DIR)


@router.on_event("startup")
async def load_prediction_models():
    """Load models on application startup."""
    try:
        predictor.load_models()
        logger.info(f"Ad performance models loaded from: {MODEL_DIR}")
    except FileNotFoundError as e:
        logger.warning(f"Could not load models - {e}")
        logger.warning(
            "Prediction endpoint will return errors until models are available."
        )
    except Exception as e:
        logger.warning(f"Error loading models - {e}")


@router.post("/forecast", response_model=PredictionResponse)
async def forecast_performance(request: PredictionRequest) -> PredictionResponse:
    """
    Predict ad performance metrics (impressions, clicks, conversions).

    Based on keywords, budget, and bid strategy, this endpoint returns projected
    performance ranges calculated using the trained models.
    """
    if not predictor.is_ready():
        raise HTTPException(
            status_code=503,
            detail="Prediction models not loaded. Please ensure model files are available.",
        )

    try:
        # Convert Pydantic models to dict format using model_dump()
        keyword_data = [kw.model_dump() for kw in request.keyword_data]

        result = predictor.predict(
            keyword_data=keyword_data,
            total_budget=request.total_budget,
            strategy=request.strategy,
            period=request.period,
        )

        return PredictionResponse(**result)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Prediction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")


@router.get("/health")
async def health_check():
    """Check if the prediction service is ready."""
    return {
        "status": "healthy" if predictor.is_ready() else "not_ready",
        "models_loaded": predictor.is_ready(),
        "model_directory": MODEL_DIR,
    }
