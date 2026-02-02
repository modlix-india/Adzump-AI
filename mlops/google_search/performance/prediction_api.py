import os
import structlog
from fastapi import APIRouter, FastAPI
from contextlib import asynccontextmanager
from mlops.google_search.performance.prediction_schemas import (
    PerformancePredictionReq,
    PerformanceAPIResponse,
)
from mlops.google_search.performance import (
    AdPerformancePredictor,
)
from oserver.utils import helpers
from exceptions.custom_exceptions import (
    ModelNotLoadedException,
)
from utils.helpers import join_url

# Configure logger
logger = structlog.get_logger()

# Global predictor instance, initialized during lifespan startup
predictor: AdPerformancePredictor = None


def get_initialized_predictor() -> AdPerformancePredictor:
    """Helper to ensure predictor is initialized and read from env at runtime."""
    global predictor
    if predictor is None:
        # Get base URL for model paths
        base_url = helpers.get_base_url()
        logger.info("performance_model_using_base_url", base_url=base_url)

        # Get relative paths from env (Lazy loading after load_dotenv)
        lgbm_path = os.getenv("AD_PREDICTOR_LGBM_PATH")
        sigmas_path = os.getenv("AD_PREDICTOR_SIGMAS_PATH")
        columns_path = os.getenv("AD_PREDICTOR_COLUMNS_PATH")

        if not all([lgbm_path, sigmas_path, columns_path]):
            logger.warning(
                "performance_model_paths_missing",
                message="One or more model paths are missing in environment variables.",
            )

        lgbm_path = join_url(base_url, lgbm_path)
        sigmas_path = join_url(base_url, sigmas_path)
        columns_path = join_url(base_url, columns_path)

        predictor = AdPerformancePredictor(
            lgbm_model_path=lgbm_path,
            sigmas_path=sigmas_path,
            columns_path=columns_path,
        )
    return predictor


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Initialize and load models
    current_predictor = get_initialized_predictor()
    try:
        await current_predictor.load_models()
        logger.info("performance_models_loaded_successfully")
    except FileNotFoundError as e:
        logger.warning("performance_models_load_file_not_found", error=str(e))
        logger.warning(
            "Service starting without models. Prediction endpoint will return errors."
        )
    except Exception as e:
        logger.warning("performance_models_load_failed", error=str(e))

    yield
    # Shutdown logic
    logger.info("prediction_service_shutdown")


router = APIRouter(
    prefix="/api/ds/prediction/performance",
    tags=["Performance Prediction"],
    lifespan=lifespan,
)


@router.post("/forecast", response_model=PerformanceAPIResponse)
async def forecast_performance(
    request: PerformancePredictionReq,
) -> PerformanceAPIResponse:
    """
    Predict ad performance metrics (impressions, clicks, conversions).
    """
    current_predictor = get_initialized_predictor()
    if not current_predictor.is_ready():
        raise ModelNotLoadedException(
            "Prediction models not loaded. Please ensure model files are available."
        )

    # Convert Pydantic models to dict format using model_dump()
    keyword_data = [kw.model_dump() for kw in request.keyword_data]

    result = current_predictor.predict(
        keyword_data=keyword_data,
        total_budget=request.total_budget,
        bid_strategy=request.bid_strategy,
        period=request.period,
    )

    return PerformanceAPIResponse(success=True, data=result)


@router.get("/health")
async def health_check():
    """Check if the prediction service is ready."""
    current_predictor = get_initialized_predictor()
    return {
        "status": "healthy" if current_predictor.is_ready() else "not_ready",
        "models_loaded": current_predictor.is_ready(),
    }
