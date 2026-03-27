"""Tests for chatv2 collect_data node."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage

from agents.chatv2.nodes.collect_data import collect_data_node
from core.chatv2.models import ChatStatus


@pytest.fixture(autouse=True)
def mock_langgraph_runtime():
    """Mock LangGraph runtime helpers since tests run outside the graph."""
    with (
        patch("agents.chatv2.nodes.collect_data.get_stream_writer") as mock_gsw,
        patch("agents.chatv2.nodes.collect_data.get_config") as mock_cfg,
        patch("agents.chatv2.nodes.collect_data._get_scrape_context", return_value=None),
    ):
        mock_gsw.return_value = MagicMock()
        mock_cfg.return_value = {"configurable": {"thread_id": "test-session"}}
        yield mock_gsw.return_value


@pytest.fixture
def base_state():
    """Base state for collect_data tests."""
    return {
        "messages": [],
        "ad_plan": {},
        "status": ChatStatus.IN_PROGRESS,
        "response_message": "",
    }


@pytest.mark.asyncio
async def test_collect_data_responds_when_user_provides_different_field(base_state):
    """
    When AI asks for business name but user provides budget,
    the system should acknowledge the budget and ask for remaining fields.
    """
    base_state["messages"] = [
        AIMessage(content="What's your business name?"),
        HumanMessage(content="my budget is 5k"),
    ]

    mock_adapter = AsyncMock()
    # First call: LLM extracts budget via tool call, empty reply
    mock_adapter.chat_with_tools.return_value = (
        "",  # Empty reply (LLM didn't include text with tool call)
        [{"name": "update_ad_plan", "args": {"budget": "5000"}, "id": "call_123"}],
        MagicMock(tool_calls=[{"name": "update_ad_plan", "args": {"budget": "5000"}, "id": "call_123"}]),
    )
    # Second call: continuation response
    mock_adapter.chat.return_value = (
        "Got it! I've noted your budget of $5,000. Could you please tell me your business name?",
        None,
    )

    with patch("agents.chatv2.nodes.collect_data.get_llm_adapter", return_value=mock_adapter):
        result = await collect_data_node(base_state)

    assert result["response_message"] != "", "Response should not be empty when user provides valid data"
    assert "ad_plan" in result
    assert result["ad_plan"].get("budget") == "5000"
    # Verify continuation was called since initial reply was empty
    assert mock_adapter.chat.called, "Should call chat() to get continuation response"


@pytest.mark.asyncio
async def test_collect_data_uses_llm_reply_when_provided(base_state):
    """When LLM provides reply with tool call, use that reply directly."""
    base_state["messages"] = [
        HumanMessage(content="I want to create a campaign for my bakery"),
    ]

    mock_adapter = AsyncMock()
    mock_adapter.chat_with_tools.return_value = (
        "Great! I've noted your business is a bakery. What's your website URL?",
        [{"name": "update_ad_plan", "args": {"productName": "bakery"}, "id": "call_123"}],
        MagicMock(tool_calls=[]),
    )

    with patch("agents.chatv2.nodes.collect_data.get_llm_adapter", return_value=mock_adapter):
        result = await collect_data_node(base_state)

    assert "bakery" in result["response_message"].lower() or "website" in result["response_message"].lower()
    assert result["ad_plan"].get("productName") == "bakery"
    # Should NOT call chat() since we already have a reply
    assert not mock_adapter.chat.called


@pytest.mark.asyncio
async def test_collect_data_handles_validation_errors(base_state):
    """When validation fails, get followup response about the error."""
    base_state["messages"] = [
        HumanMessage(content="budget is -500"),
    ]

    mock_adapter = AsyncMock()
    mock_adapter.chat_with_tools.return_value = (
        "",
        [{"name": "update_ad_plan", "args": {"budget": "-500"}, "id": "call_123"}],
        MagicMock(tool_calls=[{"name": "update_ad_plan", "args": {"budget": "-500"}, "id": "call_123"}]),
    )
    mock_adapter.chat.return_value = (
        "Budget must be a positive number. Please provide a valid budget.",
        None,
    )

    with patch("agents.chatv2.nodes.collect_data.get_llm_adapter", return_value=mock_adapter):
        with patch("agents.chatv2.nodes.collect_data.validate_fields") as mock_validate:
            mock_validate.return_value = ({}, {"budget": "must be positive"})
            result = await collect_data_node(base_state)

    assert result["response_message"] != ""
    assert "budget" not in result["ad_plan"]


def _all_fields_tool_call(platform: str = "google"):
    """Helper: mock LLM returning tool call with all 5 required fields."""
    args = {
        "productName": "Test Biz",
        "websiteURL": "https://test.com",
        "budget": "5000",
        "durationDays": "14",
        "platform": platform,
    }
    return (
        "Great, I have all the details!",
        [{"name": "update_ad_plan", "args": args, "id": "call_all"}],
        MagicMock(tool_calls=[]),
    )


@pytest.mark.asyncio
async def test_collect_data_meta_platform_routes_to_meta_business(base_state):
    """When platform=meta and all fields collected -> SELECTING_META_BUSINESS."""
    base_state["messages"] = [
        HumanMessage(content="Meta campaign for Test Biz, test.com, 5k, 14 days"),
    ]

    mock_adapter = AsyncMock()
    mock_adapter.chat_with_tools.return_value = _all_fields_tool_call("meta")

    with patch("agents.chatv2.nodes.collect_data.get_llm_adapter", return_value=mock_adapter):
        with patch("agents.chatv2.nodes.collect_data.validate_fields") as mock_validate:
            mock_validate.return_value = (
                {"productName": "Test Biz", "websiteURL": "https://test.com", "budget": "5000", "durationDays": 14, "platform": "meta"},
                {},
            )
            result = await collect_data_node(base_state)

    assert result["status"] == ChatStatus.SELECTING_PARENT_ACCOUNT
    assert result["ad_plan"]["platform"] == "meta"


@pytest.mark.asyncio
async def test_collect_data_google_platform_routes_to_mcc(base_state):
    """When platform=google and all fields collected -> SELECTING_MCC."""
    base_state["messages"] = [
        HumanMessage(content="Google campaign for Test Biz, test.com, 5k, 14 days"),
    ]

    mock_adapter = AsyncMock()
    mock_adapter.chat_with_tools.return_value = _all_fields_tool_call("google")

    with patch("agents.chatv2.nodes.collect_data.get_llm_adapter", return_value=mock_adapter):
        with patch("agents.chatv2.nodes.collect_data.validate_fields") as mock_validate:
            mock_validate.return_value = (
                {"productName": "Test Biz", "websiteURL": "https://test.com", "budget": "5000", "durationDays": 14, "platform": "google"},
                {},
            )
            result = await collect_data_node(base_state)

    assert result["status"] == ChatStatus.SELECTING_PARENT_ACCOUNT
    assert result["ad_plan"]["platform"] == "google"
