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

    async def process_message_stream(
        self, session_id: str | None, message: str
    ) -> AsyncIterator[StreamEvent]:
        """Stream chat processing as SSE events.

        If session_id is None, creates a new session and emits session_init.
        Three phases: drain pre-buffered → merged fan-in → finalize.
        """
        if not session_id:
            session_id = self._create_session()
            yield data_event("session_init", {"session_id": session_id})

        state = self._session_store.get(session_id)
        self._session_store.clear_cancelled(session_id)

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

            # Re-build full response now that competitors are confirmed.
            # The summary was held back before — now it should show.
            response = self._build_response(state)
            response.intermediate_messages = [{
                "reply": confirmation,
                "attachments": [{"type": "confirmed_competitors", "competitors": competitor_names}],
            }]
            yield done_event(**response.model_dump())
            return

        state["messages"] = list(state.get("messages", [])) + [
            HumanMessage(content=message)
        ]
        state["message_attachments"] = [{"__clear__": True}]
        state["intermediate_messages"] = [{"__clear__": True}]

        for event in self._drain_buffered_scrape_events(session_id, state, replay_history=True):
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

    def cancel(self, session_id: str) -> None:
        """Mark session for cancellation."""
        self._session_store.mark_cancelled(session_id)
        logger.info("Session marked for cancellation", session_id=session_id)

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
        """Run graph + scrape as concurrent producers, yield interleaved events.

        Returns as soon as the graph producer finishes (sentinel received).
        The scrape producer is cancelled — remaining scrape progress is picked
        up later via _emit_completion_and_remaining_scrape.
        """
        event_queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        graph_done = False

        async def graph_producer() -> None:
            try:
                async for mode, chunk in self.graph.astream(
                    state, config=config, stream_mode=["custom", "messages", "updates"]
                ):
                    for event in translate_stream_chunk(mode, chunk):
                        await event_queue.put(event)
            finally:
                await event_queue.put(None)

        async def scrape_producer() -> None:
            try:
                async for step, phase, msg in self._scrape_tasks.subscribe_progress(
                    session_id, wait_for_job=True
                ):
                    await event_queue.put(_build_scrape_event(step, phase, msg))
            finally:
                await event_queue.put(None)

        graph_task = asyncio.create_task(graph_producer())
        scrape_task = asyncio.create_task(scrape_producer())

        while True:
            item = await event_queue.get()
            if item is None:
                if not graph_done:
                    # First sentinel — check if it's the graph that finished
                    if graph_task.done():
                        graph_done = True
                        break
                    # Scrape finished first; keep waiting for graph
                    continue
            else:
                # Check for cancellation before yielding
                if self._session_store.is_cancelled(session_id):
                    graph_task.cancel()
                    if not scrape_task.done():
                        scrape_task.cancel()
                    self._session_store.clear_cancelled(session_id)
                    yield done_event(status="cancelled", reply="Operation cancelled.")
                    return
                yield item

        # Graph is done — cancel scrape producer so we don't block on it.
        # Remaining scrape progress is streamed after the done_event.
        if not scrape_task.done():
            scrape_task.cancel()

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

        # Emit done_event FIRST to unblock the user's input immediately.
        # Scrape progress events stream after — frontend handles them in the sidebar.
        buffered = self._drain_buffered_scrape_events(session_id, final_state)

        yield done_event(**self._build_response(final_state).model_dump())

        for event in buffered:
            yield event

        if self._scrape_tasks.has_active_scrape(session_id):
            partial_emitted = False
            async for step, phase, msg in self._scrape_tasks.subscribe_progress(session_id):
                yield _build_scrape_event(step, phase, msg)
                # Emit partial summary as soon as it becomes available
                if not partial_emitted:
                    partial = self._scrape_tasks.get_partial_summary(session_id)
                    if partial:
                        partial_emitted = True
                        yield data_event("website_summary", {
                            "summary": partial.get("summary", ""),
                            "business_url": final_state.get("ad_plan", {}).get("websiteURL", ""),
                            "partial": True,
                        })
            # Re-drain after scrape finishes to pick up the final result
            for event in self._drain_buffered_scrape_events(session_id, final_state):
                yield event

            # Emit analysis_complete so frontend can render a chat-visible summary card
            ad_plan = final_state.get("ad_plan", {})
            ws = ad_plan.get("websiteSummary")
            if isinstance(ws, dict) and "error" not in ws:
                yield data_event("analysis_complete", {
                    "business_name": ws.get("business_type", ""),
                    "summary": (ws.get("summary") or "")[:300],
                    "location": ws.get("location"),
                    "products": (ws.get("products_services") or [])[:5],
                })

        self._session_store.update(session_id, final_state)

    # Private helpers

    def _create_session(self) -> str:
        """Create a new chat session with initialized state. Returns session_id."""
        session_id = self._session_store.create()
        self._session_store.update(session_id, create_initial_state())
        logger.info("New chatv2 session started", session_id=session_id)
        return session_id

    def _build_response(self, state: ChatState) -> ChatResponse:
        status = ChatStatus.from_string(state.get("status", "in_progress"))
        ad_plan = state.get("ad_plan", {})
        payload = self._get_trackable_fields(ad_plan)

        account_selection = state.get("account_selection")
        location_selection = state.get("location_selection")
        reply = state.get("response_message", "")

        # Priority: location → competitors → accounts → summary.
        # Hold back lower-priority UI when a higher-priority picker should show first.
        competitors_pending = (
            "suggested_competitors" in ad_plan
            and "competitors" not in ad_plan
            and ad_plan.get("suggested_competitors")
        )
        if account_selection and (location_selection or competitors_pending):
            account_selection = None
            if competitors_pending:
                reply = "Please review and select the competitors you'd like to target."

        # Hold back summary when competitors haven't been confirmed yet
        if competitors_pending and status == ChatStatus.AWAITING_CONFIRMATION:
            reply = "Please review and select the competitors you'd like to target."
            status = ChatStatus.SELECTING_ACCOUNT  # keep status pre-confirmation

        return ChatResponse(
            status=status.value,
            reply=reply,
            collected_data=payload,
            account_selection=account_selection,
            location_selection=state.get("location_selection"),
            message_attachments=state.get("message_attachments", []),
            intermediate_messages=state.get("intermediate_messages", []),
        )

    def _get_trackable_fields(self, ad_plan: dict) -> dict:
        return {
            k: v
            for k, v in ad_plan.items()
            if k not in ["startDate", "endDate", "websiteSummary", "competitors", "suggested_competitors"]
        }

    def _drain_buffered_scrape_events(
        self, session_id: str, state: dict, *, replay_history: bool = False
    ) -> list[StreamEvent]:
        """Drain queued scrape progress and merge final result if ready.

        When *replay_history* is True, emit the full progress history first
        so the frontend can rebuild all scrape steps after an SSE reconnect.
        """
        events: list[StreamEvent] = []

        if replay_history:
            for step, phase, message in self._scrape_tasks.get_progress_history(session_id):
                events.append(_build_scrape_event(step, phase, message))

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
        elif not state.get("ad_plan", {}).get("websiteSummary"):
            # Full result not ready — emit partial summary if available
            partial = self._scrape_tasks.get_partial_summary(session_id)
            if partial:
                events.append(data_event("website_summary", {
                    "summary": partial.get("summary", ""),
                    "business_url": state.get("ad_plan", {}).get("websiteURL", ""),
                    "partial": True,
                }))

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
        # Only show competitors after all account selection is complete
        allow_statuses = {
            ChatStatus.AWAITING_CONFIRMATION, ChatStatus.AWAITING_CONFIRMATION.value,
        }
        if status not in allow_statuses:
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


SCRAPE_LABELS = {
    "scrape_pages": "Reading your website...",
    "screenshot": "Taking a look at your site...",
    "extract_metadata": "Identifying your business...",
    "extract_summary": "Understanding your products & services...",
    "resolve_geo_targets": "Mapping your target areas...",
    "save": "Saving analysis...",
}


def _build_scrape_event(step: str, phase: str, message: str) -> StreamEvent:
    """Convert a scrape progress tuple into a StreamEvent."""
    if step == "__summary_chunk__":
        return data_event("summary_chunk", {"token": message})
    if step == "__screenshot__":
        return data_event("screenshot", {"url": message})
    label = SCRAPE_LABELS.get(step, message)
    if phase == "start":
        return progress_event(node=f"scrape:{step}", phase="start", label=label)
    if phase == "end":
        return progress_event(node=f"scrape:{step}", phase="end", message=message)
    return progress_event(node=f"scrape:{step}", phase="update", message=message)


chatv2_agent = ChatV2Agent()
