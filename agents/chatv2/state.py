"""LangGraph State Schema."""

from typing import Any, TypedDict, Optional, Annotated
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage

from core.chatv2.models import ChatStatus


class ChatState(TypedDict):
    """Main state for the chat graph."""

    messages: Annotated[list[BaseMessage], add_messages]
    status: ChatStatus
    ad_plan: dict[str, Any]
    parent_account_options: list[dict]
    account_options: list[dict]
    response_message: str
    account_selection: Optional[dict[str, Any]]
    location_selection: Optional[dict[str, Any]]


def create_initial_state() -> ChatState:
    """Create a fresh initial state."""
    return ChatState(
        messages=[],
        status=ChatStatus.IN_PROGRESS,
        ad_plan={},
        parent_account_options=[],
        account_options=[],
        response_message="",
        account_selection=None,
        location_selection=None,
    )
