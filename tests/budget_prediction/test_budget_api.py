import os
import httpx
import pytest
import structlog
from dotenv import load_dotenv
from oserver.utils.helpers import get_base_url
from mlops.budget_prediction.predictor import BudgetPredictor

load_dotenv()

logger = structlog.get_logger()

BASE_URL = "http://127.0.0.1:8000"
ENDPOINT = f"{BASE_URL}/api/ds/prediction/budget/recommend"
HEALTH_ENDPOINT = f"{BASE_URL}/api/ds/prediction/budget/health"


@pytest.mark.asyncio
async def test_model_loading():
    base_url = get_base_url()
    model_rel = os.getenv("BUDGET_PREDICTOR_MODEL_PATH")

    if not model_rel:
        pytest.skip("BUDGET_PREDICTOR_MODEL_PATH not set in environment")

    def join_url(base, path):
        if not path:
            return ""
        return f"{base.rstrip('/')}/{path.lstrip('/')}" if base and path else path

    model_path = join_url(base_url, model_rel)
    logger.info("testing_budget_model_loading", model_path=model_path)

    predictor = BudgetPredictor(model_path=model_path)

    try:
        predictor.load_model()
    except Exception as e:
        pytest.fail(f"Failed to load budget model from {model_path}: {str(e)}")

    assert predictor.is_ready() is True
    assert predictor.model is not None


@pytest.mark.asyncio
async def test_prediction():
    payload = {
        "clicks": 500,
        "conversions": 10,
        "duration_days": 30,
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
        assert "status" in data
        assert data["status"] == "success"
        assert "data" in data
        assert "error" in data

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
