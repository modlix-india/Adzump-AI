import pytest
import pandas as pd
from unittest.mock import MagicMock
from services.trends.pytrends_service import pytrends_service


@pytest.fixture
def mocked_service():
    # Patch the internal client of the singleton service
    mock_client = MagicMock()
    original_instance = pytrends_service._pytrends_instance
    pytrends_service._pytrends_instance = mock_client
    yield mock_client
    # Restore after test
    pytrends_service._pytrends_instance = original_instance


@pytest.mark.asyncio
async def test_get_interest_over_time_mocked(mocked_service):
    """Verify that interest over time returns valid trend data."""
    # Setup mock DataFrame
    df = pd.DataFrame(
        {"python programming": [50], "javascript": [60]},
        index=pd.to_datetime(["2023-01-01"]),
    )
    mocked_service.interest_over_time.return_value = df

    result = await pytrends_service.get_interest_over_time(
        keywords=["python programming", "javascript"]
    )

    assert result.success is True
    assert "python programming" in result.data
    assert result.data["python programming"].avg_interest == 50.0


@pytest.mark.asyncio
async def test_get_related_queries_mocked(mocked_service):
    """Verify related queries extraction."""
    top_df = pd.DataFrame({"query": ["pm tools"], "value": [100]})
    rising_df = pd.DataFrame({"query": ["new ai"], "value": [250]})

    # Use a real dict to pass the isinstance(related_data, dict) check in the service
    mocked_service.related_queries.return_value = {
        "project management": {"top": top_df, "rising": rising_df}
    }

    result = await pytrends_service.get_related_queries("project management")
    assert result.success is True
    assert len(result.top) > 1 or result.top[0].query == "pm tools"
    assert len(result.rising) > 0


@pytest.mark.asyncio
async def test_get_trending_searches_mocked(mocked_service):
    """Verify trending searches."""
    # trending_searches returns a DF where the first column has the terms
    mock_df = pd.DataFrame({0: ["trending 1", "trending 2"]})
    mocked_service.trending_searches.return_value = mock_df

    result = await pytrends_service.get_trending_searches("united_states")
    assert result.success is True
    assert "trending 1" in result.trending_searches
