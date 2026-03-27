import asyncio
from collections.abc import AsyncIterator

from fastapi import Request
from fastapi.responses import StreamingResponse
from structlog import get_logger  # type: ignore

from core.infrastructure.session_store import SessionStore, get_session_store
from core.streaming.events import StreamEvent, error_event

logger = get_logger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 15


def sse_response(
    event_generator: AsyncIterator[StreamEvent],
    request: Request | None = None,
    session_id: str | None = None,
) -> StreamingResponse:
    """Wrap an async event generator into a FastAPI SSE StreamingResponse.

    Args:
        event_generator: Async iterator of StreamEvent objects.
        request: Optional FastAPI Request — used to read ``Last-Event-ID``
            header for replay on reconnect.
        session_id: Optional session ID — when provided, events are persisted
            to the session store for reconnection replay beyond the ring buffer.
    """
    last_event_id = _parse_last_event_id(request)
    store = get_session_store() if session_id else None
    return StreamingResponse(
        _sse_stream(event_generator, last_event_id=last_event_id, store=store, session_id=session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _sse_stream(
    events: AsyncIterator[StreamEvent],
    last_event_id: int = 0,
    store: SessionStore | None = None,
    session_id: str | None = None,
) -> AsyncIterator[str]:
    """Convert StreamEvents to SSE wire format with heartbeat and replay.

    Features:
        - Auto-incrementing ``id:`` on every event frame.
        - Heartbeat comment (``: heartbeat``) every 15 s of inactivity.
        - Persistent event log in session store for ``Last-Event-ID`` replay.
    """
    # Replay missed events from persistent store on reconnect
    if last_event_id > 0 and store and session_id:
        stored_frames = store.get_events_after(session_id, last_event_id)
        for frame in stored_frames:
            yield frame
        if stored_frames:
            logger.info("sse_replay_from_store", session_id=session_id, count=len(stored_frames), after_id=last_event_id)

    seq = last_event_id

    async def _next_event(ait: AsyncIterator[StreamEvent]) -> StreamEvent:
        return await ait.__anext__()

    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    _next_event(events), timeout=HEARTBEAT_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            except StopAsyncIteration:
                break

            seq += 1
            frame = f"id: {seq}\n{event.to_sse()}"

            if store and session_id:
                store.append_event(session_id, seq, frame)

            yield frame
            logger.debug(
                "sse_event",
                seq=seq,
                event_type=event.event,
                reconciliation_id=event.id,
            )
    except Exception as e:
        seq += 1
        logger.exception("sse_stream_error", seq=seq, error=str(e))
        frame = f"id: {seq}\n{error_event(str(e), recoverable=False).to_sse()}"
        if store and session_id:
            store.append_event(session_id, seq, frame)
        yield frame
    finally:
        yield ":\n\n"


def _parse_last_event_id(request: Request | None) -> int:
    """Extract ``Last-Event-ID`` header as an int, defaulting to 0."""
    if request is None:
        return 0
    raw = request.headers.get("Last-Event-ID", "0")
    try:
        return int(raw)
    except (ValueError, TypeError):
        return 0
