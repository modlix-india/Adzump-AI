"""Translate LangGraph stream chunks into StreamEvents.

Handles stream_mode=["custom", "messages"]:
    custom   → nodes emit structured events via get_stream_writer()
    messages → token-by-token LLM output as (AIMessageChunk, metadata)

Final state is retrieved via graph.aget_state() (MemorySaver checkpointer),
not through stream_mode — keeps the streaming loop a clean pass-through.
"""

from core.streaming.events import (
    StreamEvent,
    content_event,
    data_event,
    status_event,
    progress_event,
    tool_call_event,
)


def translate_stream_chunk(mode: str, chunk) -> list[StreamEvent]:
    """Translate a stream chunk from astream(stream_mode=[...]) into StreamEvents."""
    if mode == "custom":
        return _handle_custom_event(chunk)
    if mode == "messages":
        return _handle_message_chunk(chunk)
    return []


def _handle_custom_event(data: dict) -> list[StreamEvent]:
    """Custom events from nodes via get_stream_writer()."""
    event_type = data.get("type", "")

    if event_type == "progress":
        return [
            progress_event(
                node=data.get("node", ""),
                message=data.get("content", ""),
                phase=data.get("phase", "update"),
                label=data.get("label", ""),
            )
        ]

    if event_type == "field_update":
        return [
            data_event(
                "field_update",
                {
                    "field": data.get("field", ""),
                    "value": data.get("value"),
                    "status": data.get("status", ""),
                    "error": data.get("error"),
                },
            )
        ]

    if event_type == "status":
        return [
            status_event(
                status=data.get("status", ""),
                progress=data.get("progress", ""),
                node=data.get("node", ""),
            )
        ]

    if event_type == "tool_call":
        return [
            tool_call_event(
                name=data.get("name", ""),
                args=data.get("args", {}),
                result=data.get("result"),
            )
        ]

    return []


def _handle_message_chunk(chunk) -> list[StreamEvent]:
    """Messages mode emits (AIMessageChunk, metadata) tuples."""
    message_chunk, metadata = chunk
    content = getattr(message_chunk, "content", "")
    if content:
        node = metadata.get("langgraph_node", "")
        return [content_event(token=content, node=node)]
    return []
