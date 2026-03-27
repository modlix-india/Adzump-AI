"""Translate LangGraph stream chunks into StreamEvents.

Handles stream_mode=["custom", "messages"]:
    custom   → nodes emit structured events via get_stream_writer()
    messages → token-by-token LLM output as (AIMessageChunk, metadata)

Final state is retrieved via graph.aget_state() (MemorySaver checkpointer),
not through stream_mode — keeps the streaming loop a clean pass-through.
"""

from core.streaming.event_schemas import FieldUpdatePayload
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
    if mode == "updates":
        return _handle_state_update(chunk)
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
                FieldUpdatePayload(
                    field=data.get("field", ""),
                    value=data.get("value"),
                    status=data.get("status", "valid"),
                    error=data.get("error"),
                ),
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


_SKIP_AD_PLAN_FIELDS = frozenset({
    "startDate", "endDate", "websiteSummary",
    "competitors", "suggested_competitors",
})


def _handle_state_update(chunk: dict) -> list[StreamEvent]:
    """Handle updates stream mode: emit field_update events for ad_plan changes."""
    events: list[StreamEvent] = []
    for node_name, state_diff in chunk.items():
        if not isinstance(state_diff, dict):
            continue
        ad_plan = state_diff.get("ad_plan")
        if ad_plan and isinstance(ad_plan, dict):
            for field, value in ad_plan.items():
                if field not in _SKIP_AD_PLAN_FIELDS and value is not None:
                    events.append(
                        data_event(
                            "field_update",
                            FieldUpdatePayload(field=field, value=value, status="valid"),
                        )
                    )
        status = state_diff.get("status")
        if status:
            events.append(status_event(status=str(status), progress="", node=node_name))
    return events
