"""Typed payload schemas for SSE stream events.

Each model corresponds to one event type in the ChatV2 streaming protocol.
Used by factory functions in events.py and can be exported to TypeScript
via scripts/generate_ts_types.py.
"""

from typing import Any, Literal

from pydantic import BaseModel


class ContentPayload(BaseModel):
    token: str
    node: str = ""


class ProgressPayload(BaseModel):
    node: str
    message: str = ""
    phase: Literal["start", "update", "end"] = "update"
    label: str = ""


class FieldUpdatePayload(BaseModel):
    field: str
    value: Any
    status: Literal["valid", "pending", "invalid"] = "valid"
    error: str | None = None


class DonePayload(BaseModel):
    status: str
    reply: str = ""
    collected_data: dict[str, Any] = {}
    account_selection: dict[str, Any] | None = None
    location_selection: dict[str, Any] | None = None


class ErrorPayload(BaseModel):
    message: str
    code: int = 500
    recoverable: bool = False


class WebsiteSummaryPayload(BaseModel):
    summary: str = ""
    final_summary: str = ""
    business_url: str = ""
    business_type: str = ""
    partial: bool = False
    storage_id: str = ""


class CompetitorSelectionPayload(BaseModel):
    competitors: list[dict[str, Any]]


class SummaryChunkPayload(BaseModel):
    token: str


class ToolCallPayload(BaseModel):
    name: str
    args: dict[str, Any]
    result: Any = None


class StatusPayload(BaseModel):
    status: str
    progress: str
    node: str = ""


class StateDeltaPayload(BaseModel):
    node: str
    fields: dict[str, Any]
