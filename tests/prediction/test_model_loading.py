import os
import pytest
import structlog
from dotenv import load_dotenv
from mlops.google_search.performance import AdPerformancePredictor
from oserver.utils.helpers import get_base_url

logger = structlog.get_logger()

# Load environment variables
load_dotenv()


def join_url(base, path):
    """Helper to join base URL and relative path."""
    return f"{base.rstrip('/')}/{path.lstrip('/')}" if base and path else path


@pytest.mark.asyncio
async def test_model_loading_from_url():
    """
    Integration test to verify that models can be loaded from the configured URLs.
    This test requires the environment variables to be set correctly in .env
    and the file server/URLs to be accessible.
    """
    # 1. Get configuration
    base_url = get_base_url()
    lgbm_rel = os.getenv("AD_PREDICTOR_LGBM_PATH")
    sigmas_rel = os.getenv("AD_PREDICTOR_SIGMAS_PATH")
    columns_rel = os.getenv("AD_PREDICTOR_COLUMNS_PATH")

    # Verify config exists
    assert lgbm_rel, "AD_PREDICTOR_LGBM_PATH not set in environment"
    assert sigmas_rel, "AD_PREDICTOR_SIGMAS_PATH not set in environment"
    assert columns_rel, "AD_PREDICTOR_COLUMNS_PATH not set in environment"

    # 2. Construct URLs
    lgbm_path = join_url(base_url, lgbm_rel)
    sigmas_path = join_url(base_url, sigmas_rel)
    columns_path = join_url(base_url, columns_rel)

    logger.info(
        "testing_model_loading",
        lgbm_path=lgbm_path,
        sigmas_path=sigmas_path,
        columns_path=columns_path,
    )

    # 3. Initialize Predictor
    predictor = AdPerformancePredictor(
        lgbm_model_path=lgbm_path,
        sigmas_path=sigmas_path,
        columns_path=columns_path,
    )

    # 4. Load Models
    # This will raise an exception if download fails or pickle is invalid
    try:
        await predictor.load_models()
    except Exception as e:
        pytest.fail(f"Failed to load models: {str(e)}")

    # 5. Verify State
    assert predictor.is_ready() is True
    assert predictor.models is not None
    assert predictor.uncertainty_sigmas is not None
    assert predictor.reference_columns is not None
    assert predictor.sentence_model is not None
