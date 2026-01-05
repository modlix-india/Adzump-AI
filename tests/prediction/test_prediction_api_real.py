import httpx
import pytest

# The URL of your running server
BASE_URL = "http://127.0.0.1:8000"
ENDPOINT = f"{BASE_URL}/api/ds/prediction/performance/forecast"
HEALTH_ENDPOINT = f"{BASE_URL}/api/ds/prediction/performance/health"


@pytest.mark.asyncio
async def test_live_prediction_endpoint():
    """
    Test the live prediction API with real sample data.
    Note: Your server MUST be running (uvicorn main:app) for this to pass.
    """
    payload = {
        "keyword_data": [
            {"keyword": "luxury villas bangalore", "match_type": "Exact match"},
            {"keyword": "buy house in india", "match_type": "Broad match"},
        ],
        "total_budget": 50000,
        "bid_strategy": "Maximize Conversions",
        "period": "Monthly",
    }

    async with httpx.AsyncClient() as client:
        # 1. Test Successful Prediction
        response = await client.post(ENDPOINT, json=payload, timeout=30.0)

        # Verify success
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )

        data = response.json()
        assert data["timeframe"] == "Monthly"
        assert "budget_allocated" in data
        assert "₹" in data["budget_allocated"]  # Verify formatting
        assert "impressions" in data
        assert " - " in data["impressions"]  # Verify range formatting


@pytest.mark.asyncio
async def test_api_validation_empty_keyword():
    """Verify that Pydantic blocks empty strings automatically."""
    payload = {
        "keyword_data": [{"keyword": "", "match_type": "Exact match"}],
        "total_budget": 1000,
        "bid_strategy": "Maximize Clicks",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(ENDPOINT, json=payload)

        # Should be 422 (Validation Error) because of min_length=1
        assert response.status_code == 422
        assert "min_length" in response.text


@pytest.mark.asyncio
async def test_api_validation_empty_list():
    """Verify that Pydantic blocks empty lists automatically."""
    payload = {
        "keyword_data": [],
        "total_budget": 1000,
        "bid_strategy": "Maximize Clicks",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(ENDPOINT, json=payload)

        # Should be 422 because of min_length=1 on the list itself
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_api_health_check():
    """Verify that the prediction service health check works."""
    async with httpx.AsyncClient() as client:
        response = await client.get(HEALTH_ENDPOINT)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["models_loaded"] is True
