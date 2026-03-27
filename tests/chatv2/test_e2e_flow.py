"""
E2E tests for chatv2 campaign creation flow.

Tests the full graph via ChatV2Agent.process_message_stream():
  Google: collect_data → fetch_parent_account → select_parent_account → fetch_account → select_account → confirm
  Meta:   collect_data → fetch_parent_account → select_parent_account → fetch_account → select_account → confirm
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from agents.chatv2.chat_agent import ChatV2Agent
from core.chatv2.models import ChatStatus
from core.infrastructure.context import set_auth_context
from exceptions.custom_exceptions import SessionException

COLLECT_LLM = "agents.chatv2.nodes.collect_data.get_llm_adapter"
COLLECT_VALIDATE = "agents.chatv2.nodes.collect_data.validate_fields"
CONFIRM_LLM = "agents.chatv2.nodes.confirm.get_llm_adapter"
FETCH_PARENTS = "agents.chatv2.dependencies.fetch_mcc_accounts"
FETCH_CHILDREN = "agents.chatv2.dependencies.fetch_customer_accounts"
FETCH_META_PARENTS = "agents.chatv2.dependencies.fetch_meta_business_accounts"
FETCH_META_CHILDREN = "agents.chatv2.dependencies.fetch_meta_ad_accounts"

GOOGLE_FIELDS = {
    "platform": "google", "businessName": "TestCorp",
    "websiteURL": "https://testcorp.com", "budget": "10000", "durationDays": 14,
}
META_FIELDS = {
    "platform": "meta", "businessName": "TestCorp",
    "websiteURL": "https://testcorp.com", "budget": "10000", "durationDays": 14,
}

TWO_MCCS = [{"id": "mcc_1", "name": "MCC One"}, {"id": "mcc_2", "name": "MCC Two"}]
TWO_CUSTOMERS = [{"id": "cust_1", "name": "Customer One"}, {"id": "cust_2", "name": "Customer Two"}]
TWO_META_BIZ = [{"id": "biz_1", "name": "Biz One"}, {"id": "biz_2", "name": "Biz Two"}]
TWO_META_AD = [{"id": "act_1", "name": "Ad Acct One"}, {"id": "act_2", "name": "Ad Acct Two"}]

ONE_MCC = [{"id": "mcc_1", "name": "Only MCC"}]
ONE_CUSTOMER = [{"id": "cust_1", "name": "Only Customer"}]
ONE_META_BIZ = [{"id": "biz_1", "name": "Only Biz"}]
ONE_META_AD = [{"id": "act_1", "name": "Only Ad Acct"}]

CLIENT = "TEST01"


@pytest.fixture(autouse=True)
def _set_auth_context():
    """Set auth context so agent reads client_code from it."""
    set_auth_context(client_code=CLIENT)


async def send(agent: ChatV2Agent, session_id: str, message: str) -> SimpleNamespace:
    """Consume stream and return the done event's data as an attribute-accessible object."""
    events = [e async for e in agent.process_message_stream(session_id, message)]
    done = next((e for e in events if e.event == "done"), None)
    assert done is not None, f"No done event in stream. Events: {[e.event for e in events]}"
    return SimpleNamespace(**done.data)


def _llm_that_extracts(fields: dict):
    """Mock LLM adapter: returns a tool call that extracts all given fields."""
    adapter = AsyncMock()
    adapter.chat_with_tools.return_value = (
        "",  # no text reply (tool-only)
        [{"name": "update_ad_plan", "args": {**fields, "reasoning": "all fields"}, "id": "tc1"}],
        MagicMock(tool_calls=[{"name": "update_ad_plan", "args": fields, "id": "tc1"}]),
    )
    adapter.chat.return_value = ("Fields noted.", None)
    return adapter


def _llm_that_confirms():
    """Mock LLM adapter: calls confirm_campaign_creation tool."""
    adapter = AsyncMock()
    adapter.chat_with_tools.return_value = (
        "", [{"name": "confirm_campaign_creation", "args": {}, "id": "tc2"}], MagicMock(tool_calls=[]),
    )
    return adapter


@pytest.fixture(autouse=True)
def _mock_stream_writers():
    """Nodes use get_stream_writer() — mock it since tests run outside LangGraph."""
    with patch("agents.chatv2.nodes.collect_data.get_stream_writer") as m1, \
         patch("agents.chatv2.nodes.confirm.get_stream_writer") as m2, \
         patch("agents.chatv2.nodes.select_account.get_stream_writer") as m3:
        writer = MagicMock()
        m1.return_value = writer
        m2.return_value = writer
        m3.return_value = writer
        yield


@pytest.fixture
def agent():
    return ChatV2Agent()


@pytest.mark.asyncio
async def test_google_full_flow(agent):
    """
    Google path with multiple accounts at each step.
    Flow: collect → fetch_parent(2) → user picks → fetch_account(2) → user picks → confirm → done
    """
    session = await agent.start_session()
    sid = session["session_id"]

    # --- Step 1: collect all 5 fields → shows parent account list ---
    with patch(COLLECT_LLM, return_value=_llm_that_extracts(GOOGLE_FIELDS)), \
         patch(COLLECT_VALIDATE, new_callable=AsyncMock, return_value=(GOOGLE_FIELDS, {})), \
         patch(FETCH_PARENTS, new_callable=AsyncMock, return_value=TWO_MCCS):

        r = await send(agent, sid, "Google, TestCorp, testcorp.com, 10k, 14d")

    assert r.status == "selecting_parent_account"
    assert r.account_selection is not None
    assert r.account_selection["type"] == "parent_account"
    assert len(r.account_selection["options"]) == 2

    # --- Step 2: pick MCC → shows customer list ---
    with patch(FETCH_CHILDREN, new_callable=AsyncMock, return_value=TWO_CUSTOMERS):
        r = await send(agent, sid, "mcc_1")

    assert r.status == "selecting_account"
    assert r.account_selection["type"] == "account"
    assert len(r.account_selection["options"]) == 2

    # --- Step 3: pick customer → confirmation summary ---
    r = await send(agent, sid, "cust_1")

    assert r.status == "awaiting_confirmation"
    assert "TestCorp" in r.reply
    assert "10,000" in r.reply

    # --- Step 4: confirm → completed ---
    with patch(CONFIRM_LLM, return_value=_llm_that_confirms()):
        r = await send(agent, sid, "yes")

    assert r.status == "completed"
    assert r.collected_data["loginCustomerId"] == "mcc_1"
    assert r.collected_data["customerId"] == "cust_1"


@pytest.mark.asyncio
async def test_google_auto_select_single_accounts(agent):
    """
    Single MCC + single customer → both auto-selected → straight to confirmation.
    Flow: collect → fetch_parent(1) → auto → fetch_account(1) → auto → confirm summary
    """
    session = await agent.start_session()
    sid = session["session_id"]

    with patch(COLLECT_LLM, return_value=_llm_that_extracts(GOOGLE_FIELDS)), \
         patch(COLLECT_VALIDATE, new_callable=AsyncMock, return_value=(GOOGLE_FIELDS, {})), \
         patch(FETCH_PARENTS, new_callable=AsyncMock, return_value=ONE_MCC), \
         patch(FETCH_CHILDREN, new_callable=AsyncMock, return_value=ONE_CUSTOMER):

        r = await send(agent, sid, "Google, TestCorp, testcorp.com, 10k, 14d")

    assert r.status == "awaiting_confirmation"
    assert "TestCorp" in r.reply


@pytest.mark.asyncio
async def test_google_no_mcc_accounts(agent):
    """
    No MCC accounts → stops with error, does NOT proceed to confirm.
    Flow: collect → fetch_parent([]) → END
    """
    session = await agent.start_session()
    sid = session["session_id"]

    with patch(COLLECT_LLM, return_value=_llm_that_extracts(GOOGLE_FIELDS)), \
         patch(COLLECT_VALIDATE, new_callable=AsyncMock, return_value=(GOOGLE_FIELDS, {})), \
         patch(FETCH_PARENTS, new_callable=AsyncMock, return_value=[]):

        r = await send(agent, sid, "Google, TestCorp, testcorp.com, 10k, 14d")

    assert r.status == "in_progress", "Should NOT route to confirm when no accounts found"
    assert "couldn't find" in r.reply.lower()


@pytest.mark.asyncio
async def test_meta_full_flow(agent):
    """
    Meta path with multiple accounts at each step.
    Flow: collect → fetch_parent(2) → user picks → fetch_account(2) → user picks → confirm → done
    """
    session = await agent.start_session()
    sid = session["session_id"]

    # --- Step 1: collect all 5 fields → shows business list ---
    with patch(COLLECT_LLM, return_value=_llm_that_extracts(META_FIELDS)), \
         patch(COLLECT_VALIDATE, new_callable=AsyncMock, return_value=(META_FIELDS, {})), \
         patch(FETCH_META_PARENTS, new_callable=AsyncMock, return_value=TWO_META_BIZ):

        r = await send(agent, sid, "Meta, TestCorp, testcorp.com, 10k, 14d")

    assert r.status == "selecting_parent_account"
    assert r.account_selection["type"] == "parent_account"
    assert len(r.account_selection["options"]) == 2

    # --- Step 2: pick business → shows ad account list ---
    with patch(FETCH_META_CHILDREN, new_callable=AsyncMock, return_value=TWO_META_AD):
        r = await send(agent, sid, "biz_1")

    assert r.status == "selecting_account"
    assert r.account_selection["type"] == "account"
    assert len(r.account_selection["options"]) == 2

    # --- Step 3: pick ad account → confirmation summary ---
    r = await send(agent, sid, "act_1")

    assert r.status == "awaiting_confirmation"
    assert "TestCorp" in r.reply
    assert "Meta" in r.reply

    # --- Step 4: confirm → completed ---
    with patch(CONFIRM_LLM, return_value=_llm_that_confirms()):
        r = await send(agent, sid, "yes")

    assert r.status == "completed"
    assert r.collected_data["metaBusinessId"] == "biz_1"
    assert r.collected_data["metaAdAccountId"] == "act_1"
    assert r.collected_data["platform"] == "meta"


@pytest.mark.asyncio
async def test_meta_auto_select_single_accounts(agent):
    """
    Single business + single ad account → both auto-selected → straight to confirmation.
    Flow: collect → fetch_parent(1) → auto → fetch_account(1) → auto → confirm summary
    """
    session = await agent.start_session()
    sid = session["session_id"]

    with patch(COLLECT_LLM, return_value=_llm_that_extracts(META_FIELDS)), \
         patch(COLLECT_VALIDATE, new_callable=AsyncMock, return_value=(META_FIELDS, {})), \
         patch(FETCH_META_PARENTS, new_callable=AsyncMock, return_value=ONE_META_BIZ), \
         patch(FETCH_META_CHILDREN, new_callable=AsyncMock, return_value=ONE_META_AD):

        r = await send(agent, sid, "Meta, TestCorp, testcorp.com, 10k, 14d")

    assert r.status == "awaiting_confirmation"
    assert "TestCorp" in r.reply


@pytest.mark.asyncio
async def test_meta_no_businesses(agent):
    """
    No Meta businesses → stops with error, does NOT proceed to confirm.
    Flow: collect → fetch_parent([]) → END
    """
    session = await agent.start_session()
    sid = session["session_id"]

    with patch(COLLECT_LLM, return_value=_llm_that_extracts(META_FIELDS)), \
         patch(COLLECT_VALIDATE, new_callable=AsyncMock, return_value=(META_FIELDS, {})), \
         patch(FETCH_META_PARENTS, new_callable=AsyncMock, return_value=[]):

        r = await send(agent, sid, "Meta, TestCorp, testcorp.com, 10k, 14d")

    assert r.status == "in_progress", "Should NOT route to confirm when no businesses found"
    assert "couldn't find" in r.reply.lower()


@pytest.mark.asyncio
async def test_start_session_greeting(agent):
    """Start session returns greeting mentioning both platforms."""
    result = await agent.start_session()
    assert "session_id" in result
    assert "Google" in result["message"]
    assert "Meta" in result["message"]


@pytest.mark.asyncio
async def test_end_session(agent):
    session = await agent.start_session()
    result = await agent.end_session(session["session_id"])
    assert "ended" in result["message"].lower()


@pytest.mark.asyncio
async def test_message_after_end_raises(agent):
    session = await agent.start_session()
    sid = session["session_id"]
    await agent.end_session(sid)

    with pytest.raises(SessionException, match="can not find session"):
        agent.validate_session(sid)


@pytest.mark.asyncio
async def test_invalid_session_raises(agent):
    with pytest.raises(SessionException, match="can not find session"):
        agent.validate_session("nonexistent")
