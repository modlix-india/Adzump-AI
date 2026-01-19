import os
import structlog
from fastapi import APIRouter, FastAPI
from contextlib import asynccontextmanager
from mlops.budget.budget_schemas import (
    BudgetPredictionReq,
    BudgetPredictionData,
    BudgetAPIResponse,
)
from mlops.budget.budget_predictor import BudgetPredictor
from oserver.utils import helpers

logger = structlog.get_logger()

# Global predictor instance
predictor: BudgetPredictor = None


def get_initialized_predictor() -> BudgetPredictor:
    global predictor
    if predictor is None:
        base_url = helpers.get_base_url()
        model_rel = os.getenv("BUDGET_PREDICTOR_MODEL_PATH")

        if not model_rel:
            logger.warning("BUDGET_PREDICTOR_MODEL_PATH not set in environment")
            # Fallback or error? For now, we'll proceed but load_model will likely fail if path is None or empty
            # But let's handle None gracefully

        def join_url(base, path):
            if not path:
                return ""
            return f"{base.rstrip('/')}/{path.lstrip('/')}" if base and path else path

        model_path = join_url(base_url, model_rel)

        predictor = BudgetPredictor(model_path=model_path)
    return predictor


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize and load model
    current_predictor = get_initialized_predictor()
    if current_predictor.model_path:
        try:
            current_predictor.load_model()
            logger.info("budget_model_loaded_successfully")
        except FileNotFoundError as e:
            logger.warning("budget_model_not_found", error=str(e))
        except Exception as e:
            logger.warning("budget_model_load_failed", error=str(e))
    else:
        logger.warning("budget_model_path_missing_skipping_load")

    yield
    logger.info("budget_prediction_service_shutdown")


router = APIRouter(
    prefix="/api/ds/prediction/budget", tags=["budget-prediction"], lifespan=lifespan
)


@router.post("/recommend", response_model=BudgetAPIResponse)
async def recommend_budget(request: BudgetPredictionReq) -> BudgetAPIResponse:
    """
    Recommend a budget based on clicks, conversions, and duration.
    """
    current_predictor = get_initialized_predictor()
    if not current_predictor.is_ready():
        return BudgetAPIResponse(
            status="error", error="Budget prediction model not loaded."
        )

    try:
        result = current_predictor.predict(
            clicks=request.clicks,
            conversions=request.conversions,
            duration_days=request.duration_days,
            buffer_percent=request.buffer_percent,
        )
        return BudgetAPIResponse(
            status="success",
            data=BudgetPredictionData(
                suggested_budget=result["suggested_budget"],
                base_cost_prediction=result["base_cost_prediction"],
            ),
        )
    except Exception as e:
        logger.error("budget_prediction_error", error=str(e))
        return BudgetAPIResponse(status="error", error=f"Prediction failed: {str(e)}")


@router.get("/health")
async def health_check():
    current_predictor = get_initialized_predictor()
    return {
        "status": "healthy" if current_predictor.is_ready() else "not_ready",
        "model_loaded": current_predictor.is_ready(),
    }
