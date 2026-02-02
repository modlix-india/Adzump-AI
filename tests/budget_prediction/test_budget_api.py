import os
import httpx
import pytest
import structlog
from dotenv import load_dotenv
from oserver.utils.helpers import get_base_url
from mlops.google_search.budget_prediction.predictor import BudgetPredictor
from utils.helpers import join_url

load_dotenv()

logger = structlog.get_logger()

BASE_URL = "http://127.0.0.1:8000"
ENDPOINT = f"{BASE_URL}/api/ds/prediction/budget/"
HEALTH_ENDPOINT = f"{BASE_URL}/api/ds/prediction/budget/health"


@pytest.mark.asyncio
async def test_model_loading():
    base_url = get_base_url()
    model_path = os.getenv("BUDGET_PREDICTOR_MODEL_PATH")

    if not model_path:
        pytest.skip("BUDGET_PREDICTOR_MODEL_PATH not set in environment")

    model_path = join_url(base_url, model_path)
    logger.info("testing_budget_model_loading", model_path=model_path)

    predictor = BudgetPredictor(model_path=model_path)

    try:
        await predictor.load_model()
    except Exception as e:
        pytest.fail(f"Failed to load budget model from {model_path}: {str(e)}")

    assert predictor.is_ready() is True
    assert predictor.model is not None


@pytest.mark.asyncio
async def test_prediction():
    payload = {
        "conversions": 10,
        "duration_days": 30,
        "expected_conversion_rate": 12.0,
        "buffer_percent": 0.20,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(ENDPOINT, json=payload, timeout=30.0)
        except httpx.ConnectError:
            pytest.skip("Server not running at localhost:8000")

        assert response.status_code == 200, (
            f"Got {response.status_code}: {response.text}"
        )

        data = response.json()
        logger.info("budget_api_response", response_data=data)

        # Verify structure
        assert "success" in data
        assert data["success"] is True
        assert "data" in data

        # Verify result data
        result_data = data["data"]
        assert "suggested_budget" in result_data
        assert "base_cost_prediction" in result_data
        assert isinstance(result_data["suggested_budget"], int)
        assert result_data["suggested_budget"] > 0


@pytest.mark.asyncio
async def test_health():
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(HEALTH_ENDPOINT)
        except httpx.ConnectError:
            pytest.skip("Server not running at localhost:8000")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "model_loaded" in data
