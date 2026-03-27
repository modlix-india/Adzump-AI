"""
LangGraph state machine for campaign creation flow.

Flow Diagram:
─────────────
    Entry (_route_entry)
         │
         ├─ COMPLETED ──► END
         ├─ CONFIRMING_LOCATION ──► confirm_location ──► fetch_parent_account / END
         ├─ SELECTING_PARENT_ACCOUNT ──► select_parent_account ──► fetch_account / END
         ├─ SELECTING_ACCOUNT ──► select_account ──► show_summary ──► END
         ├─ AWAITING_CONFIRMATION ──► confirm ──► END
         │
         └─ IN_PROGRESS (default):
              collect_data (budget predicted here if needed)
                   │
                   ▼ (all fields → SELECTING_PARENT_ACCOUNT)
              confirm_location
                   │ (real estate → pause for map, else passthrough)
                   ▼
              fetch_parent_account
                   │
              ┌────┴────┐
              │ single   │ multiple / error
              ▼          ▼
         fetch_account   END (pause for parent selection)
              │
         ┌────┴────┐
         │ single   │ multiple / error
         ▼          ▼
      show_summary   END (pause for account selection)
         │
         ▼
        END
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from structlog import get_logger

from agents.chatv2.nodes import (
    collect_data_node,
    confirm_location_node,
    confirm_node,
    show_summary_node,
    fetch_parent_account_options,
    select_parent_account_node,
    fetch_account_options,
    select_account_node,
)
from agents.chatv2.state import ChatState
from core.chatv2.models import ChatStatus

logger = get_logger(__name__)

COLLECT_DATA = "collect_data"
CONFIRM_LOCATION = "confirm_location"
FETCH_PARENT_ACCOUNT = "fetch_parent_account"
SELECT_PARENT_ACCOUNT = "select_parent_account"
FETCH_ACCOUNT = "fetch_account"
SELECT_ACCOUNT = "select_account"
SHOW_SUMMARY = "show_summary"
CONFIRM = "confirm"

NODE_LABELS = {
    COLLECT_DATA: "Collecting campaign details",
    CONFIRM_LOCATION: "Confirming location",
    FETCH_PARENT_ACCOUNT: "Loading manager accounts",
    SELECT_PARENT_ACCOUNT: "Processing account selection",
    FETCH_ACCOUNT: "Loading ad accounts",
    SELECT_ACCOUNT: "Processing account selection",
    SHOW_SUMMARY: "Preparing summary",
    CONFIRM: "Processing confirmation",
}


def _wrap_node(node_name: str, node_fn):
    """Wrap a node to auto-emit step_start/step_end progress events."""

    async def wrapped(state: ChatState):
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        label = NODE_LABELS.get(node_name, node_name)
        writer({"type": "progress", "node": node_name, "phase": "start", "label": label})
        try:
            result = await node_fn(state)
            writer({"type": "progress", "node": node_name, "phase": "end"})
            return result
        except Exception:
            writer(
                {"type": "progress", "node": node_name, "phase": "end", "content": "Error"}
            )
            raise

    wrapped.__name__ = node_fn.__name__
    return wrapped


STATUS_TO_NODE = {
    ChatStatus.COMPLETED: END,
    ChatStatus.CONFIRMING_LOCATION: CONFIRM_LOCATION,
    ChatStatus.SELECTING_PARENT_ACCOUNT: SELECT_PARENT_ACCOUNT,
    ChatStatus.SELECTING_ACCOUNT: SELECT_ACCOUNT,
    ChatStatus.AWAITING_CONFIRMATION: CONFIRM,
}

_compiled_graph: CompiledStateGraph | None = None


def get_chat_graph() -> CompiledStateGraph:
    """Main entry point for accessing the chat state machine."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_graph()
    return _compiled_graph


def _build_graph() -> CompiledStateGraph:
    """Build and compile the chat state graph."""
    graph = StateGraph[ChatState, None, ChatState, ChatState](ChatState)

    graph.add_node(COLLECT_DATA, _wrap_node(COLLECT_DATA, collect_data_node))
    graph.add_node(CONFIRM_LOCATION, _wrap_node(CONFIRM_LOCATION, confirm_location_node))
    graph.add_node(FETCH_PARENT_ACCOUNT, _wrap_node(FETCH_PARENT_ACCOUNT, fetch_parent_account_options))
    graph.add_node(SELECT_PARENT_ACCOUNT, _wrap_node(SELECT_PARENT_ACCOUNT, select_parent_account_node))
    graph.add_node(FETCH_ACCOUNT, _wrap_node(FETCH_ACCOUNT, fetch_account_options))
    graph.add_node(SELECT_ACCOUNT, _wrap_node(SELECT_ACCOUNT, select_account_node))
    graph.add_node(SHOW_SUMMARY, _wrap_node(SHOW_SUMMARY, show_summary_node))
    graph.add_node(CONFIRM, _wrap_node(CONFIRM, confirm_node))

    graph.set_conditional_entry_point(
        _route_entry,
        {
            COLLECT_DATA: COLLECT_DATA,
            CONFIRM_LOCATION: CONFIRM_LOCATION,
            SELECT_PARENT_ACCOUNT: SELECT_PARENT_ACCOUNT,
            SELECT_ACCOUNT: SELECT_ACCOUNT,
            CONFIRM: CONFIRM,
            END: END,
        },
    )

    graph.add_conditional_edges(
        COLLECT_DATA,
        _route_after_collect,
        {CONFIRM_LOCATION: CONFIRM_LOCATION, END: END},
    )
    graph.add_conditional_edges(
        CONFIRM_LOCATION,
        _route_after_location,
        {FETCH_PARENT_ACCOUNT: FETCH_PARENT_ACCOUNT, END: END},
    )
    graph.add_conditional_edges(
        FETCH_PARENT_ACCOUNT,
        _route_after_parent,
        {FETCH_ACCOUNT: FETCH_ACCOUNT, END: END},
    )
    graph.add_conditional_edges(
        SELECT_PARENT_ACCOUNT,
        _route_after_parent,
        {FETCH_ACCOUNT: FETCH_ACCOUNT, END: END},
    )
    graph.add_conditional_edges(
        FETCH_ACCOUNT,
        _route_after_fetch_account,
        {SHOW_SUMMARY: SHOW_SUMMARY, END: END},
    )
    graph.add_edge(SELECT_ACCOUNT, SHOW_SUMMARY)
    graph.add_edge(SHOW_SUMMARY, END)
    graph.add_edge(CONFIRM, END)

    return graph.compile(checkpointer=MemorySaver())


def _route_entry(state: ChatState) -> str:
    """Determine which node to enter based on current status."""
    return STATUS_TO_NODE.get(_get_status(state), COLLECT_DATA)


def _route_after_collect(state: ChatState) -> str:
    """After collection: proceed to location confirmation when all fields are collected."""
    if _get_status(state) == ChatStatus.SELECTING_PARENT_ACCOUNT:
        return CONFIRM_LOCATION
    return END


def _route_after_location(state: ChatState) -> str:
    """After location: proceed to account fetch if confirmed, else pause for map."""
    if _get_status(state) == ChatStatus.SELECTING_PARENT_ACCOUNT:
        return FETCH_PARENT_ACCOUNT
    return END


def _route_after_parent(state: ChatState) -> str:
    """After parent fetch/selection: fetch children if parent selected, else pause."""
    if _get_status(state) == ChatStatus.SELECTING_ACCOUNT:
        return FETCH_ACCOUNT
    return END


def _route_after_fetch_account(state: ChatState) -> str:
    """After child fetch: show summary if auto-selected, else pause."""
    if _get_status(state) == ChatStatus.AWAITING_CONFIRMATION:
        return SHOW_SUMMARY
    return END


def _get_status(state: ChatState) -> ChatStatus:
    """Extract ChatStatus from state."""
    return state.get("status", ChatStatus.IN_PROGRESS)
