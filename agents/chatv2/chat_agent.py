"""
ChatV2Agent - Application service for chat operations.
"""

import asyncio
import json
from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage
from structlog import get_logger

from agents.chatv2.competitor_manager import get_competitor_task_manager
from agents.chatv2.graph import get_chat_graph
from agents.chatv2.scrape_manager import get_scrape_task_manager
from agents.chatv2.state import ChatState, create_initial_state
from core.chatv2.models import ChatResponse, ChatStatus, SessionResponse
from core.infrastructure.session_store import get_session_store
from core.streaming.events import StreamEvent, data_event, done_event, progress_event
from core.streaming.langgraph_translator import translate_stream_chunk
from exceptions.custom_exceptions import SessionException

logger = get_logger(__name__)

STATUS_PROGRESS = {
    ChatStatus.IN_PROGRESS: "1/3",
    ChatStatus.CONFIRMING_LOCATION: "1/3",
    ChatStatus.SELECTING_PARENT_ACCOUNT: "2/3",
    ChatStatus.SELECTING_ACCOUNT: "2/3",
    ChatStatus.AWAITING_CONFIRMATION: "3/3",
    ChatStatus.COMPLETED: "3/3",
}


class ChatV2Agent:
    """Application agent for chat operations using LangGraph state machine."""

    def __init__(self):
        self._session_store = get_session_store()
        self._scrape_tasks = get_scrape_task_manager()
        self._competitor_tasks = get_competitor_task_manager()
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

        Three phases: drain pre-buffered → merged fan-in → finalize.
        """
        state = self._session_store.get(session_id)

        competitor_names = _try_parse_competitor_selection(message)
        if competitor_names is not None:
            yield progress_event(node="competitors", phase="start", label="Saving competitors")
            ad_plan = state.get("ad_plan", {})
            ad_plan["competitors"] = competitor_names
            state["ad_plan"] = ad_plan
            self._session_store.update(session_id, state)
            yield data_event("field_update", {"field": "competitors", "value": competitor_names})
            yield progress_event(node="competitors", phase="end", message=f"{len(competitor_names)} competitor(s) saved")
            confirmation = f"Got it! {len(competitor_names)} competitor(s) saved."
            previous_question = state.get("response_message", "")
            if previous_question:
                confirmation += f"\n\n{previous_question}"
            yield done_event(
                status=state.get("status", "in_progress"),
                reply=confirmation,
                collected_data=self._get_trackable_fields(ad_plan),
                progress=self._get_progress(
                    ChatStatus.from_string(state.get("status", "in_progress"))
                ),
                account_selection=state.get("account_selection"),
            )
            return

        state["messages"] = list(state.get("messages", [])) + [
            HumanMessage(content=message)
        ]

        for event in self._drain_buffered_scrape_events(session_id, state):
            yield event

        config = {"configurable": {"thread_id": session_id}}

        async for event in self._stream_graph_and_scrape(
            state, config, session_id
        ):
            yield event

        async for event in self._emit_completion_and_remaining_scrape(
            config, session_id
        ):
            yield event

    async def get_session_details(self, session_id: str) -> SessionResponse:
        state = self._session_store.get(session_id)
        if state is None:
            raise SessionException(session_id)

        if self._merge_scrape_if_ready(session_id, state):
            self._session_store.update(session_id, state)

        ad_plan = state.get("ad_plan", {})
        status = ChatStatus.from_string(state.get("status", "in_progress"))
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

        self._scrape_tasks.cleanup(session_id)
        self._competitor_tasks.cleanup(session_id)
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

    async def _stream_graph_and_scrape(
        self, state: dict, config: dict, session_id: str
    ) -> AsyncIterator[StreamEvent]:
        """Run graph + scrape as concurrent producers, yield interleaved events."""
        event_queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()

        async def graph_producer() -> None:
            try:
                async for mode, chunk in self.graph.astream(
                    state, config=config, stream_mode=["custom", "messages"]
                ):
                    for event in translate_stream_chunk(mode, chunk):
                        await event_queue.put(event)
            finally:
                await event_queue.put(None)

        async def scrape_producer() -> None:
            try:
                async for step, phase, msg in self._scrape_tasks.subscribe_progress(session_id):
                    await event_queue.put(_build_scrape_event(step, phase, msg))
            finally:
                await event_queue.put(None)

        producers = [asyncio.create_task(graph_producer())]
        if self._scrape_tasks.has_active_scrape(session_id):
            producers.append(asyncio.create_task(scrape_producer()))

        sentinels = 0
        while sentinels < len(producers):
            item = await event_queue.get()
            if item is None:
                sentinels += 1
                continue
            yield item

        for p in producers:
            if not p.done():
                p.cancel()

    async def _emit_completion_and_remaining_scrape(
        self, config: dict, session_id: str
    ) -> AsyncIterator[StreamEvent]:
        """Yield done_event (unblocks user), then stream remaining scrape progress."""
        snapshot = await self.graph.aget_state(config)
        final_state = snapshot.values

        if not final_state:
            yield done_event(status="error", reply="No result from graph")
            return

        self._session_store.update(session_id, final_state)

        if self._scrape_tasks.has_active_scrape(session_id):
            async for step, phase, msg in self._scrape_tasks.subscribe_progress(session_id):
                yield _build_scrape_event(step, phase, msg)

        buffered = self._drain_buffered_scrape_events(session_id, final_state)

        yield done_event(**self._build_response(final_state).model_dump())

        for event in buffered:
            yield event
        self._session_store.update(session_id, final_state)

    # Private helpers

    def _build_response(self, state: ChatState) -> ChatResponse:
        status = ChatStatus.from_string(state.get("status", "in_progress"))
        ad_plan = state.get("ad_plan", {})
        payload = self._get_trackable_fields(ad_plan)

        competitors_pending = (
            "suggested_competitors" in ad_plan
            and "competitors" not in ad_plan
            and ad_plan.get("suggested_competitors")
        )

        return ChatResponse(
            status=status.value,
            reply=state.get("response_message", ""),
            collected_data=payload,
            progress=self._get_progress(status),
            account_selection=None if competitors_pending else state.get("account_selection"),
            location_selection=state.get("location_selection"),
        )

    def _get_progress(self, status: ChatStatus) -> str:
        return STATUS_PROGRESS.get(status, "1/3")

    def _get_trackable_fields(self, ad_plan: dict) -> dict:
        return {
            k: v
            for k, v in ad_plan.items()
            if k not in ["startDate", "endDate", "websiteSummary", "competitors", "suggested_competitors"]
        }

    def _drain_buffered_scrape_events(
        self, session_id: str, state: dict
    ) -> list[StreamEvent]:
        """Drain queued scrape progress and merge final result if ready."""
        events: list[StreamEvent] = []

        for step, phase, message in self._scrape_tasks.drain_progress(session_id):
            events.append(_build_scrape_event(step, phase, message))

        result = self._merge_scrape_if_ready(session_id, state)
        if result:
            if "error" in result:
                events.append(
                    data_event(
                        "field_update",
                        {
                            "field": "websiteSummary",
                            "value": "Analysis failed",
                            "status": "invalid",
                            "error": result["error"],
                        },
                    )
                )
            else:
                events.append(data_event("website_summary", result))

        competitors = self._merge_competitors_if_ready(session_id, state)
        if competitors:
            events.append(data_event("competitor_selection", {"competitors": competitors}))

        return events

    def _merge_scrape_if_ready(self, session_id: str, state: dict) -> dict | None:
        """Merge scrape result or error into ad_plan. Returns result/error dict or None."""
        ad_plan = state.get("ad_plan")
        if not ad_plan or "websiteSummary" in ad_plan:
            return None

        result = self._scrape_tasks.get_result_if_ready(session_id)
        if result:
            result_dict = result.model_dump()
            ad_plan["websiteSummary"] = result_dict
            logger.info("scrape_result_merged", session_id=session_id)
            self._competitor_tasks.start_find(session_id, result_dict)
            return result_dict

        error = self._scrape_tasks.get_error(session_id)
        if error:
            ad_plan["websiteSummary"] = {"error": error}
            logger.warning("scrape_error_merged", session_id=session_id, error=error)
            return {"error": error}

        return None

    def _merge_competitors_if_ready(
        self, session_id: str, state: dict
    ) -> list[dict] | None:
        """Return competitor list if background find is done and data collection complete."""
        ad_plan = state.get("ad_plan")
        if not ad_plan or "suggested_competitors" in ad_plan or "competitors" in ad_plan:
            return None

        status = state.get("status", ChatStatus.IN_PROGRESS)
        hold_statuses = {
            ChatStatus.IN_PROGRESS, ChatStatus.IN_PROGRESS.value,
            ChatStatus.CONFIRMING_LOCATION, ChatStatus.CONFIRMING_LOCATION.value,
        }
        if status in hold_statuses:
            return None

        result = self._competitor_tasks.get_result_if_ready(session_id)
        if result is not None:
            ad_plan["suggested_competitors"] = result
            logger.info("competitors_merged", session_id=session_id, count=len(result))
            return result

        error = self._competitor_tasks.get_error(session_id)
        if error:
            ad_plan["suggested_competitors"] = []
            logger.warning("competitor_find_failed", session_id=session_id, error=error)

        return None


def _try_parse_competitor_selection(message: str) -> list[str] | None:
    """Parse competitor confirm JSON from frontend. Returns validated name list or None."""
    try:
        parsed = json.loads(message)
        if isinstance(parsed, dict) and parsed.get("type") == "competitor_selection":
            raw = parsed.get("competitors", [])
            return [str(c).strip() for c in raw if isinstance(c, str) and c.strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _build_scrape_event(step: str, phase: str, message: str) -> StreamEvent:
    """Convert a scrape progress tuple into a StreamEvent."""
    if phase == "start":
        return progress_event(node=f"scrape:{step}", phase="start", label=message)
    return progress_event(node=f"scrape:{step}", phase="end", message=message)


chatv2_agent = ChatV2Agent()
