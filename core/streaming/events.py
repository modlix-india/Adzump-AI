from typing import Any, Literal

from pydantic import BaseModel

EventType = Literal[
    "progress", "content", "tool_call", "status", "data", "error", "done"
]


class StreamEvent(BaseModel):
    """Universal SSE event envelope. All streaming events share this shape."""

    event: EventType
    data: dict[str, Any]

    def to_sse(self) -> str:
        return f"event: {self.event}\ndata: {self.model_dump_json()}\n\n"


def progress_event(
    node: str, message: str = "", phase: str = "update", label: str = ""
) -> StreamEvent:
    return StreamEvent(
        event="progress",
        data={"node": node, "message": message, "phase": phase, "label": label},
    )


def content_event(token: str, node: str = "") -> StreamEvent:
    return StreamEvent(event="content", data={"token": token, "node": node})


def tool_call_event(name: str, args: dict, result: Any = None) -> StreamEvent:
    return StreamEvent(
        event="tool_call", data={"name": name, "args": args, "result": result}
    )


def status_event(status: str, progress: str, node: str = "") -> StreamEvent:
    return StreamEvent(
        event="status", data={"status": status, "progress": progress, "node": node}
    )


def data_event(data_type: str, payload: dict) -> StreamEvent:
    return StreamEvent(event="data", data={"type": data_type, "payload": payload})


def error_event(
    message: str, code: int = 500, recoverable: bool = False
) -> StreamEvent:
    return StreamEvent(
        event="error",
        data={"message": message, "code": code, "recoverable": recoverable},
    )


def done_event(**payload) -> StreamEvent:
    return StreamEvent(event="done", data=payload)
