import os
import structlog
from fastapi import APIRouter, HTTPException, FastAPI
from contextlib import asynccontextmanager
from mlops.prediction_schemas import PredictionRequest, PredictionResponse
from mlops.ad_performance_predictor import AdPerformancePredictor
from oserver.utils import helpers

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
        logger.info("using_base_url_for_models", base_url=base_url)

        # Get relative paths from env (Lazy loading after load_dotenv)
        lgbm_rel = os.getenv("AD_PREDICTOR_LGBM_PATH")
        sigmas_rel = os.getenv("AD_PREDICTOR_SIGMAS_PATH")
        columns_rel = os.getenv("AD_PREDICTOR_COLUMNS_PATH")

        if not all([lgbm_rel, sigmas_rel, columns_rel]):
            logger.warning(
                "One or more model paths are missing in environment variables."
            )

        # Construct full URLs
        def join_url(base, path):
            return f"{base.rstrip('/')}/{path.lstrip('/')}" if base and path else path

        lgbm_path = join_url(base_url, lgbm_rel)
        sigmas_path = join_url(base_url, sigmas_rel)
        columns_path = join_url(base_url, columns_rel)

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
        current_predictor.load_models()
        logger.info("models_loaded_successfully")
    except FileNotFoundError as e:
        logger.warning("models_load_file_not_found", error=str(e))
        logger.warning(
            "Service starting without models. Prediction endpoint will return errors."
        )
    except Exception as e:
        logger.warning("models_load_failed", error=str(e))

    yield
    # Shutdown logic
    logger.info("prediction_service_shutdown")


router = APIRouter(prefix="/api/ds/prediction", tags=["prediction"], lifespan=lifespan)


@router.post("/forecast", response_model=PredictionResponse)
async def forecast_performance(request: PredictionRequest) -> PredictionResponse:
    """
    Predict ad performance metrics (impressions, clicks, conversions).

    """
    current_predictor = get_initialized_predictor()
    if not current_predictor.is_ready():
        raise HTTPException(
            status_code=503,
            detail="Prediction models not loaded. Please ensure model files are available.",
        )

    try:
        # Convert Pydantic models to dict format using model_dump()
        keyword_data = [kw.model_dump() for kw in request.keyword_data]

        result = current_predictor.predict(
            keyword_data=keyword_data,
            total_budget=request.total_budget,
            strategy=request.strategy,
            period=request.period,
        )

        return PredictionResponse(**result)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("prediction_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")


@router.get("/health")
async def health_check():
    """Check if the prediction service is ready."""
    current_predictor = get_initialized_predictor()
    return {
        "status": "healthy" if current_predictor.is_ready() else "not_ready",
        "models_loaded": current_predictor.is_ready(),
    }
