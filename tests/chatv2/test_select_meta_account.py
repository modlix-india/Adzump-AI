"""Tests for account selection nodes with Meta platform config."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agents.chatv2.nodes.select_parent_account import (
    fetch_parent_account_options,
    select_parent_account_node,
)
from agents.chatv2.nodes.select_account import (
    fetch_account_options,
    select_account_node,
)
from core.chatv2.models import ChatStatus, AccountType
from core.infrastructure.context import set_auth_context


@pytest.fixture(autouse=True)
def _set_auth_context():
    set_auth_context(client_code="TEST")


@pytest.fixture(autouse=True)
def mock_stream_writer():
    """Mock get_stream_writer since tests run outside LangGraph runtime."""
    with patch("agents.chatv2.nodes.select_parent_account.get_stream_writer") as mock_parent, \
         patch("agents.chatv2.nodes.select_account.get_stream_writer") as mock_child:
        writer = MagicMock()
        mock_parent.return_value = writer
        mock_child.return_value = writer
        yield writer


COMPLETE_AD_PLAN = {
    "businessName": "Test Biz",
    "websiteURL": "https://test.com",
    "budget": "5000",
    "durationDays": 14,
    "platform": "meta",
}

SAMPLE_BUSINESSES = [
    {"id": "biz_1", "name": "Business One"},
    {"id": "biz_2", "name": "Business Two"},
]

SAMPLE_AD_ACCOUNTS = [
    {"id": "act_1", "name": "Ad Account One"},
    {"id": "act_2", "name": "Ad Account Two"},
]


def _make_message(content: str):
    """Create a simple message object with .content attribute."""
    msg = MagicMock()
    msg.content = content
    return msg


@pytest.mark.asyncio
@patch("agents.chatv2.dependencies.fetch_meta_business_accounts", new_callable=AsyncMock)
async def test_fetch_business_empty_list(mock_fetch):
    """No businesses found -> IN_PROGRESS status, empty options."""
    mock_fetch.return_value = []
    state = {"ad_plan": {"platform": "meta"}}

    result = await fetch_parent_account_options(state)

    assert result["status"] == ChatStatus.IN_PROGRESS
    assert result["parent_account_options"] == []
    assert result["account_selection"] is None


@pytest.mark.asyncio
@patch("agents.chatv2.dependencies.fetch_meta_business_accounts", new_callable=AsyncMock)
async def test_fetch_business_single_auto_selects(mock_fetch_biz):
    """Single business -> auto-select parent, proceed to account fetch."""
    single_biz = [{"id": "biz_1", "name": "Only Biz"}]
    mock_fetch_biz.return_value = single_biz

    state = {"ad_plan": dict(COMPLETE_AD_PLAN)}

    result = await fetch_parent_account_options(state)

    assert result["ad_plan"]["metaBusinessId"] == "biz_1"
    assert result["status"] == ChatStatus.SELECTING_ACCOUNT
    assert "Only Biz" in result["response_message"]


@pytest.mark.asyncio
@patch("agents.chatv2.dependencies.fetch_meta_business_accounts", new_callable=AsyncMock)
async def test_fetch_business_multiple_shows_selection(mock_fetch):
    """Multiple businesses -> SELECTING_PARENT_ACCOUNT with account_selection."""
    mock_fetch.return_value = SAMPLE_BUSINESSES
    state = {"ad_plan": {"platform": "meta"}}

    result = await fetch_parent_account_options(state)

    assert result["status"] == ChatStatus.SELECTING_PARENT_ACCOUNT
    assert len(result["parent_account_options"]) == 2
    assert result["account_selection"]["type"] == AccountType.PARENT_ACCOUNT


@pytest.mark.asyncio
@patch("agents.chatv2.dependencies.fetch_meta_ad_accounts", new_callable=AsyncMock)
async def test_fetch_ad_accounts_single_auto_selects(mock_fetch):
    """Single ad account -> auto-select, AWAITING_CONFIRMATION."""
    mock_fetch.return_value = [{"id": "act_1", "name": "Only Account"}]
    state = {
        "ad_plan": {**COMPLETE_AD_PLAN, "metaBusinessId": "biz_1"},
        "parent_account_options": SAMPLE_BUSINESSES,
    }

    result = await fetch_account_options(state)

    assert result["ad_plan"]["metaAdAccountId"] == "act_1"
    assert result["status"] == ChatStatus.AWAITING_CONFIRMATION
    assert result["account_selection"] is None


@pytest.mark.asyncio
async def test_select_business_valid():
    """Valid business selection -> sets parent ID, proceeds to account fetch."""
    state = {
        "messages": [_make_message("biz_1")],
        "parent_account_options": SAMPLE_BUSINESSES,
        "ad_plan": dict(COMPLETE_AD_PLAN),
    }

    result = await select_parent_account_node(state)

    assert result["ad_plan"]["metaBusinessId"] == "biz_1"
    assert result["status"] == ChatStatus.SELECTING_ACCOUNT


@pytest.mark.asyncio
async def test_select_business_invalid():
    """Invalid selection -> re-show business list."""
    state = {
        "messages": [_make_message("invalid_id")],
        "parent_account_options": SAMPLE_BUSINESSES,
        "ad_plan": dict(COMPLETE_AD_PLAN),

    }

    result = await select_parent_account_node(state)

    assert "Invalid" in result["response_message"]
    assert result["account_selection"]["type"] == AccountType.PARENT_ACCOUNT


@pytest.mark.asyncio
async def test_select_business_no_messages():
    """No messages -> prompt user to select."""
    state = {
        "messages": [],
        "parent_account_options": SAMPLE_BUSINESSES,
        "ad_plan": {"platform": "meta"},

    }

    result = await select_parent_account_node(state)

    assert "select" in result["response_message"].lower()
    assert result["account_selection"]["type"] == AccountType.PARENT_ACCOUNT


@pytest.mark.asyncio
async def test_select_business_valid_sets_name():
    """Valid business selection -> response includes selected name."""
    state = {
        "messages": [_make_message("biz_1")],
        "parent_account_options": SAMPLE_BUSINESSES,
        "ad_plan": dict(COMPLETE_AD_PLAN),
    }

    result = await select_parent_account_node(state)

    assert "Business One" in result["response_message"]


@pytest.mark.asyncio
async def test_fetch_ad_accounts_no_business_id():
    """No business_id -> prompt user to select business first."""
    state = {
        "ad_plan": {"platform": "meta"},
        "parent_account_options": SAMPLE_BUSINESSES,

    }

    result = await fetch_account_options(state)

    assert result["status"] == ChatStatus.SELECTING_PARENT_ACCOUNT
    assert "business" in result["response_message"].lower()


@pytest.mark.asyncio
@patch("agents.chatv2.dependencies.fetch_meta_ad_accounts", new_callable=AsyncMock)
async def test_fetch_ad_accounts_has_accounts(mock_fetch):
    """Business has ad accounts -> SELECTING_ACCOUNT."""
    mock_fetch.return_value = SAMPLE_AD_ACCOUNTS
    state = {
        "ad_plan": {"platform": "meta", "metaBusinessId": "biz_1"},
        "parent_account_options": SAMPLE_BUSINESSES,

    }

    result = await fetch_account_options(state)

    assert result["status"] == ChatStatus.SELECTING_ACCOUNT
    assert len(result["account_options"]) == 2
    assert result["account_selection"]["type"] == AccountType.ACCOUNT


@pytest.mark.asyncio
@patch("agents.chatv2.dependencies.fetch_meta_ad_accounts", new_callable=AsyncMock)
async def test_fetch_ad_accounts_empty(mock_fetch):
    """No ad accounts -> fall back to SELECTING_PARENT_ACCOUNT."""
    mock_fetch.return_value = []
    state = {
        "ad_plan": {"platform": "meta", "metaBusinessId": "biz_1"},
        "parent_account_options": SAMPLE_BUSINESSES,

    }

    result = await fetch_account_options(state)

    assert result["status"] == ChatStatus.SELECTING_PARENT_ACCOUNT
    assert result["account_options"] == []


@pytest.mark.asyncio
async def test_select_ad_account_valid_all_fields():
    """Valid selection with all fields -> AWAITING_CONFIRMATION."""
    ad_plan = {
        **COMPLETE_AD_PLAN,
        "metaBusinessId": "biz_1",
    }
    state = {
        "messages": [_make_message("act_1")],
        "account_options": SAMPLE_AD_ACCOUNTS,
        "ad_plan": ad_plan,
    }

    result = await select_account_node(state)

    assert result["ad_plan"]["metaAdAccountId"] == "act_1"
    assert result["status"] == ChatStatus.AWAITING_CONFIRMATION


@pytest.mark.asyncio
async def test_select_ad_account_valid_missing_fields():
    """Valid selection but missing base fields -> IN_PROGRESS."""
    state = {
        "messages": [_make_message("act_1")],
        "account_options": SAMPLE_AD_ACCOUNTS,
        "ad_plan": {"platform": "meta", "metaBusinessId": "biz_1"},
    }

    result = await select_account_node(state)

    assert result["ad_plan"]["metaAdAccountId"] == "act_1"
    assert result["status"] == ChatStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_select_ad_account_invalid():
    """Invalid selection -> re-show ad account list."""
    state = {
        "messages": [_make_message("bad_id")],
        "account_options": SAMPLE_AD_ACCOUNTS,
        "ad_plan": dict(COMPLETE_AD_PLAN),
    }

    result = await select_account_node(state)

    assert "Invalid" in result["response_message"]
    assert result["account_selection"]["type"] == AccountType.ACCOUNT


@pytest.mark.asyncio
async def test_select_ad_account_no_messages():
    """No messages -> prompt user to select."""
    state = {
        "messages": [],
        "account_options": SAMPLE_AD_ACCOUNTS,
        "ad_plan": {"platform": "meta"},
    }

    result = await select_account_node(state)

    assert "select" in result["response_message"].lower()
    assert result["account_selection"]["type"] == AccountType.ACCOUNT
