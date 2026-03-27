"""LangGraph State Schema."""

from typing import Any, TypedDict, Optional, Annotated
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage

from core.chatv2.models import ChatStatus


def _append_list(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Reducer: append new items. Pass sentinel '__clear__' to reset."""
    if new and new[0].get("__clear__"):
        return []
    return existing + new


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
    message_attachments: Annotated[list[dict[str, Any]], _append_list]
    intermediate_messages: Annotated[list[dict[str, Any]], _append_list]


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
        message_attachments=[],
        intermediate_messages=[],
    )
