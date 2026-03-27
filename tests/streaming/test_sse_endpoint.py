"""Tests for SSE streaming: sse.py wrapper + chatv2 /stream endpoint integration."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from core.streaming.events import (
    StreamEvent,
    content_event,
    done_event,
    error_event,
    progress_event,
)
from core.streaming.sse import (
    _sse_stream,
    _buffer_append,
    replay_missed_events,
    EVENT_BUFFER_MAX_SIZE,
)
from core.chatv2.models import ChatStatus


class TestSseStream:
    """Unit tests for _sse_stream — the error-safe SSE wrapper."""

    @pytest.mark.asyncio
    async def test_yields_sse_formatted_events_with_ids(self):
        async def mock_events():
            yield progress_event(node="collect_data", message="Thinking...")
            yield content_event(token="Hi there")

        chunks = [chunk async for chunk in _sse_stream(mock_events())]

        assert len(chunks) == 3  # 2 events + final comment
        assert chunks[0].startswith("id: 1\nevent: progress")
        assert chunks[1].startswith("id: 2\nevent: content")
        assert chunks[2] == ":\n\n"

    @pytest.mark.asyncio
    async def test_catches_mid_stream_error_with_id(self):
        async def failing_events():
            yield progress_event(node="collect_data")
            raise RuntimeError("LLM crashed")

        chunks = [chunk async for chunk in _sse_stream(failing_events())]

        assert len(chunks) == 3  # progress + error + final comment
        assert chunks[0].startswith("id: 1\nevent: progress")
        assert "id: 2\n" in chunks[1]
        assert "event: error" in chunks[1]
        # Parse error data — skip id: line and event: line
        data_line = [l for l in chunks[1].split("\n") if l.startswith("data: ")][0]
        error_data = json.loads(data_line.removeprefix("data: "))
        assert "LLM crashed" in error_data["data"]["message"]
        assert chunks[2] == ":\n\n"

    @pytest.mark.asyncio
    async def test_always_ends_with_comment_line(self):
        async def empty_events():
            return
            yield  # make it an async generator

        chunks = [chunk async for chunk in _sse_stream(empty_events())]
        assert chunks == [":\n\n"]

    @pytest.mark.asyncio
    async def test_sequential_ids_increment(self):
        async def mock_events():
            yield progress_event(node="a")
            yield progress_event(node="b")
            yield progress_event(node="c")

        chunks = [chunk async for chunk in _sse_stream(mock_events())]

        assert chunks[0].startswith("id: 1\n")
        assert chunks[1].startswith("id: 2\n")
        assert chunks[2].startswith("id: 3\n")


class TestStreamEndpoint:
    """Integration tests for POST /{session_id}/stream using httpx + mock graph."""

    @pytest.fixture
    def mock_session_store(self):
        store = MagicMock()
        store.get.return_value = {
            "messages": [],
            "status": ChatStatus.IN_PROGRESS,
            "ad_plan": {},
            "response_message": "",

            "parent_account_options": [],
            "account_options": [],
            "account_selection": None,
        }
        store.exists.return_value = True
        return store

    def _make_final_state(self):
        return {
            "messages": [],
            "status": ChatStatus.IN_PROGRESS,
            "ad_plan": {},
            "response_message": "Hello!",
            "parent_account_options": [],
            "account_options": [],
            "account_selection": None,
        }

    def _make_stream_chunks(self):
        """Simulate astream(stream_mode=["custom", "messages"]) output."""
        return [
            ("custom", {"type": "progress", "node": "collect_data", "content": "Analyzing message..."}),
            ("messages", (SimpleNamespace(content="Hello!"), {"langgraph_node": "collect_data"})),
        ]

    @pytest.mark.asyncio
    async def test_stream_endpoint_returns_sse_content_type(self, mock_session_store):
        final_state = self._make_final_state()

        async def mock_astream(state, config=None, stream_mode=None):
            for chunk in self._make_stream_chunks():
                yield chunk

        mock_graph = MagicMock()
        mock_graph.astream = mock_astream
        mock_graph.aget_state = AsyncMock(return_value=SimpleNamespace(values=final_state))

        with (
            patch("agents.chatv2.chat_agent.get_session_store", return_value=mock_session_store),
            patch("agents.chatv2.chat_agent.get_chat_graph", return_value=mock_graph),
        ):
            from agents.chatv2.chat_agent import ChatV2Agent
            agent = ChatV2Agent()
            agent._graph = mock_graph
            agent._session_store = mock_session_store

            with patch("api.chatv2.chatv2_agent", agent):
                from api.chatv2 import router
                from fastapi import FastAPI
                app = FastAPI()
                app.include_router(router)

                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/ds/chatv2/test-session/stream",
                        params={"message": "hi", "clientCode": "TEST"},
                    )

                    assert response.status_code == 200
                    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
                    assert response.headers["cache-control"] == "no-cache"
                    assert response.headers["x-accel-buffering"] == "no"

    @pytest.mark.asyncio
    async def test_stream_endpoint_produces_expected_event_sequence(self, mock_session_store):
        final_state = self._make_final_state()

        async def mock_astream(state, config=None, stream_mode=None):
            for chunk in self._make_stream_chunks():
                yield chunk

        mock_graph = MagicMock()
        mock_graph.astream = mock_astream
        mock_graph.aget_state = AsyncMock(return_value=SimpleNamespace(values=final_state))

        with (
            patch("agents.chatv2.chat_agent.get_session_store", return_value=mock_session_store),
            patch("agents.chatv2.chat_agent.get_chat_graph", return_value=mock_graph),
        ):
            from agents.chatv2.chat_agent import ChatV2Agent
            agent = ChatV2Agent()
            agent._graph = mock_graph
            agent._session_store = mock_session_store

            with patch("api.chatv2.chatv2_agent", agent):
                from api.chatv2 import router
                from fastapi import FastAPI
                app = FastAPI()
                app.include_router(router)

                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/ds/chatv2/test-session/stream",
                        params={"message": "hi", "clientCode": "TEST"},
                    )

                    body = response.text
                    parsed_events = _parse_sse_body(body)

                    event_types = [e["event"] for e in parsed_events]
                    assert "progress" in event_types
                    assert "content" in event_types
                    assert "done" in event_types
                    assert event_types[-1] == "done"

    @pytest.mark.asyncio
    async def test_stream_endpoint_invalid_session(self, mock_session_store):
        mock_session_store.get.return_value = None

        with (
            patch("agents.chatv2.chat_agent.get_session_store", return_value=mock_session_store),
            patch("agents.chatv2.chat_agent.get_chat_graph", return_value=MagicMock()),
        ):
            from agents.chatv2.chat_agent import ChatV2Agent
            agent = ChatV2Agent()
            agent._session_store = mock_session_store

            with patch("api.chatv2.chatv2_agent", agent):
                from api.chatv2 import router
                from fastapi import FastAPI
                from exceptions.handlers import setup_exception_handlers
                app = FastAPI()
                app.include_router(router)
                setup_exception_handlers(app)

                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/ds/chatv2/invalid-session/stream",
                        params={"message": "hi", "clientCode": "TEST"},
                    )

                    assert response.status_code == 401
                    body = response.json()
                    assert "session" in body["error"].lower()

    @pytest.mark.asyncio
    async def test_stream_endpoint_completed_session(self, mock_session_store):
        state = mock_session_store.get.return_value
        state["status"] = ChatStatus.COMPLETED

        with (
            patch("agents.chatv2.chat_agent.get_session_store", return_value=mock_session_store),
            patch("agents.chatv2.chat_agent.get_chat_graph", return_value=MagicMock()),
        ):
            from agents.chatv2.chat_agent import ChatV2Agent
            agent = ChatV2Agent()
            agent._session_store = mock_session_store

            with patch("api.chatv2.chatv2_agent", agent):
                from api.chatv2 import router
                from fastapi import FastAPI
                from exceptions.handlers import setup_exception_handlers
                app = FastAPI()
                app.include_router(router)
                setup_exception_handlers(app)

                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/ds/chatv2/test-session/stream",
                        params={"message": "hi", "clientCode": "TEST"},
                    )

                    assert response.status_code == 401
                    assert "completed" in response.json()["error"].lower()


class TestProcessMessageStream:
    """Unit tests for ChatV2Agent.process_message_stream async generator."""

    def _make_final_state(self):
        return {
            "messages": [],
            "status": ChatStatus.IN_PROGRESS,
            "ad_plan": {},
            "response_message": "Hi",
            "parent_account_options": [],
            "account_options": [],
            "account_selection": None,
        }

    @pytest.mark.asyncio
    async def test_yields_translated_events_and_done(self):
        final_state = self._make_final_state()

        async def mock_astream(state, config=None, stream_mode=None):
            yield ("custom", {"type": "progress", "node": "collect_data", "content": "Analyzing..."})
            yield ("messages", (SimpleNamespace(content="Hi"), {"langgraph_node": "collect_data"}))

        mock_graph = MagicMock()
        mock_graph.astream = mock_astream
        mock_graph.aget_state = AsyncMock(return_value=SimpleNamespace(values=final_state))

        mock_store = MagicMock()
        mock_store.get.return_value = {
            "messages": [],
            "status": ChatStatus.IN_PROGRESS,
            "ad_plan": {},
            "response_message": "",
        }

        from agents.chatv2.chat_agent import ChatV2Agent
        agent = ChatV2Agent()
        agent._graph = mock_graph
        agent._session_store = mock_store

        events = []
        async for event in agent.process_message_stream("test-session", "hi"):
            events.append(event)

        event_types = [e.event for e in events]
        assert "progress" in event_types
        assert "content" in event_types
        assert event_types[-1] == "done"

        mock_store.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_graph_exception_caught_by_sse_stream(self):
        """Mid-stream exceptions bubble up from process_message_stream,
        caught by _sse_stream safety net (the real error boundary)."""
        async def failing_astream(state, config=None, stream_mode=None):
            yield ("custom", {"type": "progress", "node": "collect_data", "content": "Starting..."})
            raise RuntimeError("Graph exploded")

        mock_graph = MagicMock()
        mock_graph.astream = failing_astream

        mock_store = MagicMock()
        mock_store.get.return_value = {
            "messages": [],
            "status": ChatStatus.IN_PROGRESS,
            "ad_plan": {},
            "response_message": "",
        }

        from agents.chatv2.chat_agent import ChatV2Agent
        agent = ChatV2Agent()
        agent._graph = mock_graph
        agent._session_store = mock_store

        chunks = [chunk async for chunk in _sse_stream(
            agent.process_message_stream("s1", "hi")
        )]

        assert any("event: error" in c for c in chunks)
        error_chunk = next(c for c in chunks if "event: error" in c)
        data_line = [l for l in error_chunk.split("\n") if l.startswith("data: ")][0]
        error_data = json.loads(data_line.removeprefix("data: "))
        assert "Graph exploded" in error_data["data"]["message"]


class TestSseHeartbeat:
    """Tests for SSE heartbeat on inactivity."""

    @pytest.mark.asyncio
    async def test_heartbeat_emitted_on_inactivity(self):
        """When the source generator stalls, heartbeat comments are emitted."""
        heartbeat_sent = asyncio.Event()

        async def slow_events():
            yield progress_event(node="a")
            # Stall long enough for a heartbeat
            await heartbeat_sent.wait()
            yield content_event(token="done")

        chunks: list[str] = []
        async for chunk in _sse_stream(slow_events()):
            chunks.append(chunk)
            if chunk == ": heartbeat\n\n":
                heartbeat_sent.set()
            if len(chunks) > 5:
                heartbeat_sent.set()
                break

        assert ": heartbeat\n\n" in chunks

    @pytest.mark.asyncio
    async def test_heartbeat_is_valid_sse_comment(self):
        """Heartbeat must be a valid SSE comment (colon-prefixed)."""
        async def stalling_events():
            await asyncio.sleep(20)
            return
            yield  # make it an async generator

        chunks = []
        async for chunk in _sse_stream(stalling_events()):
            chunks.append(chunk)
            if chunk.startswith(":") and "heartbeat" in chunk:
                break

        heartbeat = chunks[-1]
        assert heartbeat.startswith(":")
        assert heartbeat.endswith("\n\n")

    @pytest.mark.asyncio
    async def test_no_heartbeat_when_events_flow_fast(self):
        """If events arrive faster than 15s, no heartbeat should appear."""
        async def fast_events():
            for i in range(5):
                yield progress_event(node=f"step_{i}")

        chunks = [chunk async for chunk in _sse_stream(fast_events())]
        assert ": heartbeat\n\n" not in chunks


class TestLastEventIdReplay:
    """Tests for Last-Event-ID skip and replay buffer."""

    @pytest.mark.asyncio
    async def test_events_after_last_event_id_are_yielded(self):
        """With last_event_id=2, events 1-2 are skipped, 3+ yielded."""
        async def mock_events():
            yield progress_event(node="a")
            yield progress_event(node="b")
            yield content_event(token="c")

        chunks = [chunk async for chunk in _sse_stream(mock_events(), last_event_id=2)]
        # Only event 3 + final comment
        event_chunks = [c for c in chunks if c != ":\n\n"]
        assert len(event_chunks) == 1
        assert event_chunks[0].startswith("id: 3\n")

    @pytest.mark.asyncio
    async def test_last_event_id_zero_yields_all(self):
        """last_event_id=0 (default) yields every event."""
        async def mock_events():
            yield progress_event(node="a")
            yield content_event(token="b")

        chunks = [chunk async for chunk in _sse_stream(mock_events(), last_event_id=0)]
        event_chunks = [c for c in chunks if c != ":\n\n"]
        assert len(event_chunks) == 2

    @pytest.mark.asyncio
    async def test_last_event_id_beyond_total_yields_none(self):
        """If last_event_id exceeds total events, nothing is yielded."""
        async def mock_events():
            yield progress_event(node="a")

        chunks = [chunk async for chunk in _sse_stream(mock_events(), last_event_id=99)]
        event_chunks = [c for c in chunks if c != ":\n\n"]
        assert len(event_chunks) == 0


class TestEventBuffer:
    """Tests for the ring buffer helpers."""

    def test_buffer_append_within_limit(self):
        buf: list[tuple[int, str]] = []
        for i in range(1, 11):
            _buffer_append(buf, i, f"frame-{i}")
        assert len(buf) == 10
        assert buf[0] == (1, "frame-1")

    def test_buffer_evicts_oldest_when_full(self):
        buf: list[tuple[int, str]] = []
        for i in range(1, EVENT_BUFFER_MAX_SIZE + 10):
            _buffer_append(buf, i, f"frame-{i}")
        assert len(buf) == EVENT_BUFFER_MAX_SIZE
        # Oldest should have been evicted
        assert buf[0][0] == 10  # first 9 evicted

    def test_replay_missed_events_filters_correctly(self):
        buf = [(1, "a"), (2, "b"), (3, "c"), (4, "d")]
        result = replay_missed_events(buf, after_id=2)
        assert result == ["c", "d"]

    def test_replay_missed_events_empty_when_caught_up(self):
        buf = [(1, "a"), (2, "b")]
        result = replay_missed_events(buf, after_id=5)
        assert result == []


def _parse_sse_body(body: str) -> list[dict]:
    """Parse SSE text body into list of event dicts."""
    events = []
    for block in body.strip().split("\n\n"):
        block = block.strip()
        if not block or block == ":":
            continue
        data_line = None
        for line in block.split("\n"):
            if line.startswith("data: "):
                data_line = line.removeprefix("data: ")
        if data_line:
            try:
                events.append(json.loads(data_line))
            except json.JSONDecodeError:
                continue
    return events
