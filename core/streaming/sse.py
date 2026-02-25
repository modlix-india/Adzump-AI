from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse
from structlog import get_logger

from core.streaming.events import StreamEvent, error_event

logger = get_logger(__name__)


def sse_response(event_generator: AsyncIterator[StreamEvent]) -> StreamingResponse:
    """Wrap an async event generator into a FastAPI SSE StreamingResponse."""
    return StreamingResponse(
        _sse_stream(event_generator),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _sse_stream(events: AsyncIterator[StreamEvent]) -> AsyncIterator[str]:
    """Convert StreamEvents to SSE wire format with error safety net."""
    try:
        async for event in events:
            yield event.to_sse()
    except Exception as e:
        logger.exception("SSE stream error: %s", e)
        yield error_event(str(e), recoverable=False).to_sse()
    finally:
        yield ":\n\n"
