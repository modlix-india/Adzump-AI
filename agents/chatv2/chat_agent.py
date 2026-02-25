"""
ChatV2Agent - Application service for chat operations.
"""

from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage
from structlog import get_logger

from agents.chatv2.graph import get_chat_graph
from agents.chatv2.state import ChatState, create_initial_state
from core.chatv2.models import ChatResponse, ChatStatus, SessionResponse
from core.infrastructure.session_store import get_session_store
from core.streaming.events import StreamEvent, done_event
from core.streaming.langgraph_translator import translate_stream_chunk
from exceptions.custom_exceptions import SessionException

logger = get_logger(__name__)

STATUS_PROGRESS = {
    ChatStatus.IN_PROGRESS: "1/3",
    ChatStatus.SELECTING_PARENT_ACCOUNT: "2/3",
    ChatStatus.SELECTING_ACCOUNT: "2/3",
    ChatStatus.AWAITING_CONFIRMATION: "3/3",
    ChatStatus.COMPLETED: "3/3",
}


class ChatV2Agent:
    """Application agent for chat operations using LangGraph state machine."""

    def __init__(self):
        self._session_store = get_session_store()
        self._graph = None

    @property
    def graph(self):
        if self._graph is None:
            self._graph = get_chat_graph()
        return self._graph

    async def start_session(self) -> dict:
        """Create a new chat session with initialized state."""
        session_id = self._session_store.create()

        chat_state: ChatState = create_initial_state()
        self._session_store.update(session_id, chat_state)

        logger.info("New chatv2 session started", session_id=session_id)
        return {
            "session_id": session_id,
            "message": (
                "Hi! I'll help you set up a Google Ads or Meta campaign. "
                "First, which platform would you like to advertise on \u2014 Google or Meta?"
            ),
        }

    async def process_message_stream(
        self, session_id: str, message: str
    ) -> AsyncIterator[StreamEvent]:
        """Stream chat processing as SSE events.

        Session validation must happen before calling this (via validate_session).
        Mid-stream errors are caught by the SSE wrapper in sse.py.
        """
        state = self._session_store.get(session_id)
        state["messages"] = list(state.get("messages", [])) + [
            HumanMessage(content=message)
        ]

        config = {"configurable": {"thread_id": session_id}}
        logger.info("Starting stream processing", session_id=session_id)

        # TODO: migrate to astream_events(version="v2") for built-in observability
        #       (node lifecycle, tool calls, LLM tokens as structured events)
        async for mode, chunk in self.graph.astream(
            state, config=config, stream_mode=["custom", "messages"]
        ):
            for stream_event in translate_stream_chunk(mode, chunk):
                yield stream_event

        snapshot = await self.graph.aget_state(config)
        final_state = snapshot.values

        if final_state:
            self._session_store.update(session_id, final_state)
            response = self._build_response(final_state)
            yield done_event(**response.model_dump())
        else:
            yield done_event(status="error", reply="No result from graph")

    async def get_session_details(self, session_id: str) -> SessionResponse:
        state = self._session_store.get(session_id)
        if state is None:
            raise SessionException(session_id)

        ad_plan = state.get("ad_plan", {})
        status = ChatStatus.from_string(state.get("status", "in_progress"))

        if status in (ChatStatus.AWAITING_CONFIRMATION, ChatStatus.COMPLETED):
            payload = ad_plan
        else:
            payload = self._get_trackable_fields(ad_plan) or None

        last_activity = self._session_store.get_last_activity(session_id)

        return SessionResponse(
            status=status.value,
            data=payload,
            progress=self._get_progress(status),
            last_activity=last_activity.isoformat() if last_activity else None,
        )

    async def end_session(self, session_id: str) -> dict:
        if not self._session_store.exists(session_id):
            raise SessionException(session_id)

        self._session_store.delete(session_id)
        logger.info("Chatv2 session ended", session_id=session_id)
        return {"message": f"Session {session_id} ended successfully."}

    def validate_session(self, session_id: str) -> None:
        """Raise SessionException if session is missing or completed."""
        state = self._session_store.get(session_id)
        if state is None:
            raise SessionException(session_id, "can not find session")

        status = ChatStatus.from_string(state.get("status", "in_progress"))
        if status == ChatStatus.COMPLETED:
            raise SessionException(session_id, "campaign already completed")

    def _build_response(self, state: ChatState) -> ChatResponse:
        status = ChatStatus.from_string(state.get("status", "in_progress"))
        ad_plan = state.get("ad_plan", {})

        if status in (ChatStatus.COMPLETED, ChatStatus.AWAITING_CONFIRMATION):
            payload = ad_plan
        else:
            payload = self._get_trackable_fields(ad_plan)

        return ChatResponse(
            status=status.value,
            reply=state.get("response_message", ""),
            collected_data=payload,
            progress=self._get_progress(status),
            account_selection=state.get("account_selection"),
        )

    def _get_progress(self, status: ChatStatus) -> str:
        return STATUS_PROGRESS.get(status, "1/3")

    def _get_trackable_fields(self, ad_plan: dict) -> dict:
        return {k: v for k, v in ad_plan.items() if k not in ["startDate", "endDate"]}


chatv2_agent = ChatV2Agent()
