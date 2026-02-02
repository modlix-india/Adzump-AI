import os
import structlog
from fastapi import APIRouter, FastAPI
from contextlib import asynccontextmanager
from mlops.google_search.budget_prediction.schemas import (
    BudgetPredictionReq,
    BudgetAPIResponse,
)
from mlops.google_search.budget_prediction.predictor import BudgetPredictor
from oserver.utils import helpers
from exceptions.custom_exceptions import ModelNotLoadedException

logger = structlog.get_logger()

# Global predictor instance
predictor: BudgetPredictor = None


def get_initialized_predictor() -> BudgetPredictor:
    global predictor
    if predictor is None:
        base_url = helpers.get_base_url()
        model_rel = os.getenv("BUDGET_PREDICTOR_MODEL_PATH")

        if not model_rel:
            logger.warning(
                "budget_predictor_model_path_missing",
                message="BUDGET_PREDICTOR_MODEL_PATH not set in environment",
            )

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
            await current_predictor.load_model()
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
    prefix="/api/ds/prediction/budget",
    tags=["Budget Prediction"],
    lifespan=lifespan,
)


@router.post("/", response_model=BudgetAPIResponse)
async def recommend_budget(request: BudgetPredictionReq) -> BudgetAPIResponse:
    """
    Recommend a budget based on clicks, conversions, and duration.
    """
    current_predictor = get_initialized_predictor()
    if not current_predictor.is_ready():
        raise ModelNotLoadedException("Budget prediction model not loaded.")

    result = current_predictor.predict(
        conversions=request.conversions,
        duration_days=request.duration_days,
        expected_conversion_rate=request.expected_conversion_rate,
        buffer_percent=request.buffer_percent,
    )
    return BudgetAPIResponse(
        success=True,
        data=result,
    )


@router.get("/health")
async def health_check():
    current_predictor = get_initialized_predictor()
    return {
        "status": "healthy" if current_predictor.is_ready() else "not_ready",
        "model_loaded": current_predictor.is_ready(),
    }
