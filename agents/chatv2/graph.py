"""
LangGraph state machine for campaign creation flow.

Flow Diagram:
─────────────
    Entry (_route_entry)
         │
         ├─ COMPLETED ──► END
         ├─ CONFIRMING_LOCATION ──► confirm_location ──► predict_budget / END
         ├─ SELECTING_PARENT_ACCOUNT ──► select_parent_account ──► fetch_account / END
         ├─ SELECTING_ACCOUNT ──► select_account ──► show_summary ──► END
         ├─ AWAITING_CONFIRMATION ──► confirm ──► END
         │
         └─ IN_PROGRESS (default):
              collect_data
                   │
                   ▼ (all fields → SELECTING_PARENT_ACCOUNT)
              confirm_location
                   │ (real estate → pause for map, else passthrough)
                   ▼
              predict_budget
                   │ (Google + targetLeads → predict, else passthrough)
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
    predict_budget_node,
    confirm_node,
    show_summary_node,
    fetch_parent_account_options,
    select_parent_account_node,
    fetch_account_options,
    select_account_node,
    fetch_fb_pages_options,
    select_fb_page_node,
    fetch_ig_pages_options,
    select_ig_page_node,
    fetch_pixel_options,
    select_pixel_node,
)
from agents.chatv2.state import ChatState
from core.chatv2.models import ChatStatus

logger = get_logger(__name__)

COLLECT_DATA = "collect_data"
CONFIRM_LOCATION = "confirm_location"
PREDICT_BUDGET = "predict_budget"
FETCH_PARENT_ACCOUNT = "fetch_parent_account"
SELECT_PARENT_ACCOUNT = "select_parent_account"
FETCH_ACCOUNT = "fetch_account"
SELECT_ACCOUNT = "select_account"
FETCH_FB_PAGE = "fetch_fb_page"
SELECT_FB_PAGE = "select_fb_page"
FETCH_IG_PAGE = "fetch_ig_page"
SELECT_IG_PAGE = "select_ig_page"
FETCH_PIXEL = "fetch_pixel"
SELECT_PIXEL = "select_pixel"
SHOW_SUMMARY = "show_summary"
CONFIRM = "confirm"

STATUS_TO_NODE = {
    ChatStatus.COMPLETED: END,
    ChatStatus.CONFIRMING_LOCATION: CONFIRM_LOCATION,
    ChatStatus.SELECTING_PARENT_ACCOUNT: SELECT_PARENT_ACCOUNT,
    ChatStatus.SELECTING_FB_PAGE: SELECT_FB_PAGE,
    ChatStatus.SELECTING_IG_PAGE: SELECT_IG_PAGE,
    ChatStatus.SELECTING_ACCOUNT: SELECT_ACCOUNT,
    ChatStatus.SELECTING_PIXEL: SELECT_PIXEL,
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

    graph.add_node(COLLECT_DATA, collect_data_node)
    graph.add_node(CONFIRM_LOCATION, confirm_location_node)
    graph.add_node(PREDICT_BUDGET, predict_budget_node)
    graph.add_node(FETCH_PARENT_ACCOUNT, fetch_parent_account_options)
    graph.add_node(SELECT_PARENT_ACCOUNT, select_parent_account_node)
    graph.add_node(FETCH_ACCOUNT, fetch_account_options)
    graph.add_node(SELECT_ACCOUNT, select_account_node)
    graph.add_node(FETCH_FB_PAGE, fetch_fb_pages_options)
    graph.add_node(SELECT_FB_PAGE, select_fb_page_node)
    graph.add_node(FETCH_IG_PAGE, fetch_ig_pages_options)
    graph.add_node(SELECT_IG_PAGE, select_ig_page_node)
    graph.add_node(FETCH_PIXEL, fetch_pixel_options)
    graph.add_node(SELECT_PIXEL, select_pixel_node)
    graph.add_node(SHOW_SUMMARY, show_summary_node)
    graph.add_node(CONFIRM, confirm_node)

    graph.set_conditional_entry_point(
        _route_entry,
        {
            COLLECT_DATA: COLLECT_DATA,
            CONFIRM_LOCATION: CONFIRM_LOCATION,
            SELECT_PARENT_ACCOUNT: SELECT_PARENT_ACCOUNT,
            SELECT_FB_PAGE: SELECT_FB_PAGE,
            SELECT_IG_PAGE: SELECT_IG_PAGE,
            SELECT_ACCOUNT: SELECT_ACCOUNT,
            SELECT_PIXEL: SELECT_PIXEL,
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
        {PREDICT_BUDGET: PREDICT_BUDGET, END: END},
    )
    graph.add_conditional_edges(
        PREDICT_BUDGET,
        _route_after_predict,
        {FETCH_PARENT_ACCOUNT: FETCH_PARENT_ACCOUNT, END: END},
    )
    graph.add_conditional_edges(
        FETCH_PARENT_ACCOUNT,
        _route_after_parent,
        {
            FETCH_ACCOUNT: FETCH_ACCOUNT,
            FETCH_FB_PAGE: FETCH_FB_PAGE,
            END: END,
        },
    )
    graph.add_conditional_edges(
        SELECT_PARENT_ACCOUNT,
        _route_after_parent,
        {
            FETCH_ACCOUNT: FETCH_ACCOUNT,
            FETCH_FB_PAGE: FETCH_FB_PAGE,
            END: END,
        },
    )
    graph.add_conditional_edges(
        FETCH_FB_PAGE,
        _route_after_fb_page,
        {FETCH_IG_PAGE: FETCH_IG_PAGE, END: END},
    )
    graph.add_conditional_edges(
        SELECT_FB_PAGE,
        _route_after_fb_page,
        {FETCH_IG_PAGE: FETCH_IG_PAGE, END: END},
    )
    graph.add_conditional_edges(
        FETCH_IG_PAGE,
        _route_after_ig_page,
        {
            FETCH_ACCOUNT: FETCH_ACCOUNT,
            FETCH_PIXEL: FETCH_PIXEL,
            SHOW_SUMMARY: SHOW_SUMMARY,
            END: END,
        },
    )
    graph.add_conditional_edges(
        SELECT_IG_PAGE,
        _route_after_ig_page,
        {
            FETCH_ACCOUNT: FETCH_ACCOUNT,
            FETCH_PIXEL: FETCH_PIXEL,
            SHOW_SUMMARY: SHOW_SUMMARY,
            END: END,
        },
    )
    graph.add_conditional_edges(
        FETCH_ACCOUNT,
        _route_after_fetch_account,
        {
            FETCH_PIXEL: FETCH_PIXEL,
            SHOW_SUMMARY: SHOW_SUMMARY,
            FETCH_FB_PAGE: FETCH_FB_PAGE,
            END: END,
        },
    )
    graph.add_conditional_edges(
        SELECT_ACCOUNT,
        _route_after_fetch_account,
        {
            FETCH_PIXEL: FETCH_PIXEL,
            SHOW_SUMMARY: SHOW_SUMMARY,
            FETCH_FB_PAGE: FETCH_FB_PAGE,
            END: END,
        },
    )
    graph.add_conditional_edges(
        FETCH_PIXEL,
        _route_after_pixel,
        {SHOW_SUMMARY: SHOW_SUMMARY, END: END},
    )
    graph.add_conditional_edges(
        SELECT_PIXEL,
        _route_after_pixel,
        {SHOW_SUMMARY: SHOW_SUMMARY, END: END},
    )
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
    """After location: proceed to budget prediction if confirmed, else pause for map."""
    if _get_status(state) == ChatStatus.SELECTING_PARENT_ACCOUNT:
        return PREDICT_BUDGET
    return END


def _route_after_predict(state: ChatState) -> str:
    """After prediction: proceed to account fetch if budget is set, else back to collect."""
    if _get_status(state) == ChatStatus.SELECTING_PARENT_ACCOUNT:
        return FETCH_PARENT_ACCOUNT
    return END


def _route_after_parent(state: ChatState) -> str:
    """After parent fetch/selection: fetch FB pages (Meta) or accounts (Google or manual)."""
    status = _get_status(state)

    if status == ChatStatus.SELECTING_FB_PAGE:
        return FETCH_FB_PAGE
    if status == ChatStatus.SELECTING_ACCOUNT:
        return FETCH_ACCOUNT
    return END


def _route_after_fb_page(state: ChatState) -> str:
    """After FB page: fetch IG accounts if selected, else pause."""
    if _get_status(state) == ChatStatus.SELECTING_IG_PAGE:
        return FETCH_IG_PAGE
    return END


def _route_after_ig_page(state: ChatState) -> str:
    """After IG page: fetch ad accounts if selected, or fetch pixels if Meta, else summary."""
    status = _get_status(state)
    if status == ChatStatus.SELECTING_ACCOUNT:
        return FETCH_ACCOUNT
    if status == ChatStatus.SELECTING_PIXEL:
        return FETCH_PIXEL
    if status == ChatStatus.AWAITING_CONFIRMATION:
        return SHOW_SUMMARY
    return END


def _route_after_fetch_account(state: ChatState) -> str:
    """After child fetch: show/fetch pixel (Meta) or show summary (others)."""
    status = _get_status(state)
    if status == ChatStatus.SELECTING_PIXEL:
        return FETCH_PIXEL
    if status == ChatStatus.AWAITING_CONFIRMATION:
        return SHOW_SUMMARY
    if status == ChatStatus.SELECTING_FB_PAGE:
        return FETCH_FB_PAGE
    return END


def _route_after_pixel(state: ChatState) -> str:
    """After pixel fetch/selection: proceed to summary."""
    if _get_status(state) == ChatStatus.AWAITING_CONFIRMATION:
        return SHOW_SUMMARY
    return END


def _get_status(state: ChatState) -> ChatStatus:
    """Extract ChatStatus from state."""
    return state.get("status", ChatStatus.IN_PROGRESS)
