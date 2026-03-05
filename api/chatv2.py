from typing import Any

from fastapi import APIRouter

from agents.chatv2.chat_agent import chatv2_agent
from core.streaming.sse import sse_response
from utils.response_helpers import success_response

router = APIRouter(prefix="/api/ds/chatv2", tags=["chatv2"])

# TODO: merge start-session into /stream — first message auto-creates session,
#       eliminating the extra round trip before the user sees a response.


@router.post("/start-session")
async def start_session() -> dict[str, Any]:
    result = await chatv2_agent.start_session()
    return success_response(data=result)


@router.post("/{session_id}/stream")
async def stream_chat_process(session_id: str, message: str):
    """Process a chat message with SSE streaming response."""
    chatv2_agent.validate_session(session_id)
    event_stream = chatv2_agent.process_message_stream(session_id, message)
    return sse_response(event_stream)


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
