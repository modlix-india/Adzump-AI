from typing import Any, Optional

from fastapi import APIRouter, Query, Request

from agents.chatv2.chat_agent import chatv2_agent
from core.streaming.sse import sse_response
from utils.response_helpers import success_response

router = APIRouter(prefix="/api/ds/chatv2", tags=["chatv2"])


@router.post("/stream")
async def stream_chat(
    message: str,
    request: Request,
    session_id: Optional[str] = Query(None),
):
    """Single chat endpoint — auto-creates session if none provided.

    First message: omit session_id → creates session, emits session_init event.
    Subsequent messages: pass session_id → continues existing session.
    """
    if session_id:
        chatv2_agent.validate_session(session_id)

    return sse_response(
        chatv2_agent.process_message_stream(session_id, message),
        request=request,
        session_id=session_id or "",
    )


@router.post("/{session_id}/cancel")
async def cancel_session(session_id: str):
    """Cancel an in-progress chat operation."""
    chatv2_agent.validate_session(session_id)
    chatv2_agent.cancel(session_id)
    return success_response(data={"cancelled": True})


@router.get("/{session_id}")
async def get_session_details(session_id: str) -> dict[str, Any]:
    """Get current session status (read-only)."""
    result = await chatv2_agent.get_session_details(session_id)
    return success_response(data=result.model_dump())


@router.post("/end-session/{session_id}")
async def end_session(session_id: str) -> dict[str, Any]:
    """End and cleanup a chat session."""
    result = await chatv2_agent.end_session(session_id)
    return success_response(data=result)
