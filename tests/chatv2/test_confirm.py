"""Tests for confirm node — campaign confirmation flow."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from agents.chatv2.nodes.confirm import confirm_node, build_summary, show_summary_node
from core.chatv2.models import ChatStatus, AccountType


@pytest.fixture(autouse=True)
def mock_stream_writer():
    """Mock get_stream_writer since tests run outside LangGraph runtime."""
    with patch("agents.chatv2.nodes.confirm.get_stream_writer") as mock_gsw:
        mock_gsw.return_value = MagicMock()
        yield mock_gsw.return_value


COMPLETE_AD_PLAN = {
    "businessName": "Valmark Cityville",
    "websiteURL": "https://cityville.in",
    "budget": "12000",
    "durationDays": 50,
    "platform": "google",
    "loginCustomerId": "4461972633",
    "customerId": "4220436668",
}

SAMPLE_MCC_ACCOUNTS = [
    {"id": "4461972633", "name": "Modlix"},
]

SAMPLE_CUSTOMER_ACCOUNTS = [
    {"id": "4220436668", "name": "Fincity Common Ads"},
    {"id": "4220436669", "name": "Other Account"},
]


@pytest.fixture
def confirmed_state():
    """State at confirmation stage with all fields and accounts selected."""
    return {
        "messages": [],
        "ad_plan": dict(COMPLETE_AD_PLAN),
        "status": ChatStatus.AWAITING_CONFIRMATION,
        "response_message": "",
        "parent_account_options": SAMPLE_MCC_ACCOUNTS,
        "account_options": SAMPLE_CUSTOMER_ACCOUNTS,
    }


def _mock_tool_call(name, args=None):
    return {"name": name, "args": args or {}, "id": "call_123"}


def _mock_llm(tool_name=None, tool_args=None, ai_content=""):
    """Create a mock LLM adapter returning the given tool call."""
    adapter = AsyncMock()
    tool_calls = [_mock_tool_call(tool_name, tool_args)] if tool_name else []
    adapter.chat_with_tools.return_value = (ai_content, tool_calls, MagicMock())
    return adapter


@pytest.mark.asyncio
async def test_wrong_account_directly_shows_account_list(confirmed_state):
    """'wrong customer account' should immediately show account options.

    Must NOT ask 'What would you like to change?' — user already specified what's wrong.
    Regression: 'wrong' matched rejection before account change detection.
    """
    summary = build_summary(COMPLETE_AD_PLAN, confirmed_state)
    confirmed_state["messages"] = [
        AIMessage(content=summary),
        HumanMessage(content="wrong customer account"),
    ]

    mock_adapter = _mock_llm("handle_account_selection", {"action": "account"})

    with patch("agents.chatv2.nodes.confirm.get_llm_adapter", return_value=mock_adapter):
        result = await confirm_node(confirmed_state)

    assert result["status"] == ChatStatus.SELECTING_ACCOUNT
    assert result["account_selection"]["type"] == AccountType.ACCOUNT
    assert len(result["account_selection"]["options"]) == len(SAMPLE_CUSTOMER_ACCOUNTS)
    assert "customerId" not in result["ad_plan"]
    assert "customer" in result["response_message"].lower()


@pytest.mark.asyncio
async def test_wrong_account_typo_also_works(confirmed_state):
    """Typos like 'wrong customer caccout' should still trigger account change."""
    confirmed_state["messages"] = [
        AIMessage(content="I have the following details..."),
        HumanMessage(content="wrong customer caccout"),
    ]

    mock_adapter = _mock_llm("handle_account_selection", {"action": "account"})

    with patch("agents.chatv2.nodes.confirm.get_llm_adapter", return_value=mock_adapter):
        result = await confirm_node(confirmed_state)

    assert result["status"] == ChatStatus.SELECTING_ACCOUNT
    assert "customerId" not in result["ad_plan"]


@pytest.mark.asyncio
async def test_yes_after_raised_issue_does_not_confirm(confirmed_state):
    """'yes' after user raised an account issue should NOT finalize the campaign.

    Regression: 'yes' was matched as confirmation regardless of prior context.
    """
    confirmed_state["messages"] = [
        AIMessage(content="I have the following details..."),
        HumanMessage(content="wrong customer account"),
        AIMessage(content="What would you like to change?"),
        HumanMessage(content="yes change the customer account"),
    ]

    mock_adapter = _mock_llm("handle_account_selection", {"action": "account"})

    with patch("agents.chatv2.nodes.confirm.get_llm_adapter", return_value=mock_adapter):
        result = await confirm_node(confirmed_state)

    assert result["status"] == ChatStatus.SELECTING_ACCOUNT
    assert result["status"] != ChatStatus.COMPLETED
    assert "customerId" not in result["ad_plan"]


@pytest.mark.asyncio
async def test_give_me_options_triggers_account_change(confirmed_state):
    """'give me options' should show account options, NOT trigger scope restriction.

    Regression: treated as unrelated request, got 'I can only help with advertising campaigns.'
    """
    confirmed_state["messages"] = [
        AIMessage(content="I have the following details..."),
        HumanMessage(content="wrong customer account"),
        AIMessage(content="What would you like to change?"),
        HumanMessage(content="give me options"),
    ]

    mock_adapter = _mock_llm("handle_account_selection", {"action": "account"})

    with patch("agents.chatv2.nodes.confirm.get_llm_adapter", return_value=mock_adapter):
        result = await confirm_node(confirmed_state)

    assert result["status"] == ChatStatus.SELECTING_ACCOUNT
    assert result["account_selection"]["type"] == AccountType.ACCOUNT
    assert len(result["account_selection"]["options"]) == len(SAMPLE_CUSTOMER_ACCOUNTS)
    assert "customerId" not in result["ad_plan"]


@pytest.mark.asyncio
async def test_confirm_campaign_sets_completed(confirmed_state):
    """Pure confirmation -> COMPLETED status with finalized ad_plan."""
    confirmed_state["messages"] = [
        AIMessage(content="I have the following details..."),
        HumanMessage(content="looks good"),
    ]

    mock_adapter = _mock_llm("confirm_campaign_creation")

    with patch("agents.chatv2.nodes.confirm.get_llm_adapter", return_value=mock_adapter):
        result = await confirm_node(confirmed_state)

    assert result["status"] == ChatStatus.COMPLETED
    assert result["ad_plan"]["budget"] == 12000
    assert "startDate" in result["ad_plan"]
    assert "endDate" in result["ad_plan"]


@pytest.mark.asyncio
async def test_change_parent_account_resets_both_accounts(confirmed_state):
    """Changing parent account should clear both parent and child IDs."""
    confirmed_state["messages"] = [
        AIMessage(content="I have the following details..."),
        HumanMessage(content="change manager account"),
    ]

    mock_adapter = _mock_llm("handle_account_selection", {"action": "parent_account"})

    with patch("agents.chatv2.nodes.confirm.get_llm_adapter", return_value=mock_adapter):
        result = await confirm_node(confirmed_state)

    assert result["status"] == ChatStatus.SELECTING_PARENT_ACCOUNT
    assert result["account_selection"]["type"] == AccountType.PARENT_ACCOUNT
    assert "loginCustomerId" not in result["ad_plan"]
    assert "customerId" not in result["ad_plan"]


@pytest.mark.asyncio
async def test_no_tool_call_returns_ai_message(confirmed_state):
    """No tool call from LLM -> return AI's clarification text."""
    confirmed_state["messages"] = [
        AIMessage(content="I have the following details..."),
        HumanMessage(content="hmm"),
    ]

    mock_adapter = _mock_llm(ai_content="What would you like to change?")

    with patch("agents.chatv2.nodes.confirm.get_llm_adapter", return_value=mock_adapter):
        result = await confirm_node(confirmed_state)

    assert result["response_message"] == "What would you like to change?"
    assert "status" not in result


@pytest.mark.asyncio
async def test_no_tool_call_no_content_falls_back(confirmed_state):
    """No tool call and empty AI content -> fallback message."""
    confirmed_state["messages"] = [
        AIMessage(content="I have the following details..."),
        HumanMessage(content="..."),
    ]

    mock_adapter = _mock_llm(ai_content="")

    with patch("agents.chatv2.nodes.confirm.get_llm_adapter", return_value=mock_adapter):
        result = await confirm_node(confirmed_state)

    assert result["response_message"] == "What would you like to change?"


@pytest.mark.asyncio
async def test_field_modification_updates_ad_plan(confirmed_state):
    """update_ad_plan tool call should update the field and rebuild summary."""
    confirmed_state["messages"] = [
        AIMessage(content="I have the following details..."),
        HumanMessage(content="change budget to 20000"),
    ]

    mock_adapter = _mock_llm("update_ad_plan", {"budget": "20000"})

    with patch("agents.chatv2.nodes.confirm.get_llm_adapter", return_value=mock_adapter):
        with patch("agents.chatv2.nodes.confirm.validate_fields") as mock_validate:
            mock_validate.return_value = ({"budget": "20000"}, {})
            result = await confirm_node(confirmed_state)

    assert result["ad_plan"]["budget"] == "20000"
    assert "20,000" in result["response_message"]


@pytest.mark.asyncio
async def test_platform_change_clears_old_account_fields(confirmed_state):
    """Changing platform from google to meta should clear Google account IDs
    and restart account selection for the new platform.

    Regression: platform changed but loginCustomerId/customerId stayed in ad_plan.
    """
    confirmed_state["messages"] = [
        AIMessage(content="I have the following details..."),
        HumanMessage(content="yes I want to create add on meta"),
    ]

    mock_adapter = _mock_llm("update_ad_plan", {"platform": "meta"})

    with patch("agents.chatv2.nodes.confirm.get_llm_adapter", return_value=mock_adapter):
        with patch("agents.chatv2.nodes.confirm.validate_fields") as mock_validate:
            mock_validate.return_value = ({"platform": "meta"}, {})
            result = await confirm_node(confirmed_state)

    assert result["ad_plan"]["platform"] == "meta"
    assert "loginCustomerId" not in result["ad_plan"]
    assert "customerId" not in result["ad_plan"]
    assert result["status"] == ChatStatus.SELECTING_PARENT_ACCOUNT
    assert result["parent_account_options"] == []
    assert result["account_options"] == []


def test_build_summary_google():
    """Summary should format all fields with labels."""
    state = {
        "parent_account_options": SAMPLE_MCC_ACCOUNTS,
        "account_options": SAMPLE_CUSTOMER_ACCOUNTS,
    }
    summary = build_summary(COMPLETE_AD_PLAN, state)

    assert "Google Ads" in summary
    assert "Valmark Cityville" in summary
    assert "12,000" in summary
    assert "50 days" in summary
    assert "Modlix" in summary
    assert "Fincity Common Ads" in summary
    assert "Please confirm" in summary


def test_build_summary_meta():
    """Summary for Meta platform should use Meta-specific labels."""
    ad_plan = {
        "businessName": "Test Biz",
        "websiteURL": "https://test.com",
        "budget": "5000",
        "durationDays": 14,
        "platform": "meta",
        "metaBusinessId": "biz_1",
        "metaAdAccountId": "act_1",
    }
    state = {
        "parent_account_options": [{"id": "biz_1", "name": "My Business"}],
        "account_options": [{"id": "act_1", "name": "Ad Account One"}],
    }
    summary = build_summary(ad_plan, state)

    assert "Meta Ads" in summary
    assert "My Business" in summary
    assert "Ad Account One" in summary


@pytest.mark.asyncio
async def test_show_summary_node_returns_formatted_summary(confirmed_state):
    """show_summary_node should return the built summary."""
    result = await show_summary_node(confirmed_state)

    assert "Valmark Cityville" in result["response_message"]
    assert "12,000" in result["response_message"]
    assert len(result["messages"]) == 1
