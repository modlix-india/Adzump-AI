"""Tests for core.streaming.events — StreamEvent model, factory functions, SSE serialization."""

import json

import pytest

from core.streaming.events import (
    StreamEvent,
    content_event,
    data_event,
    done_event,
    error_event,
    status_event,
    progress_event,
    tool_call_event,
)


class TestStreamEventModel:

    def test_create_with_valid_event_type(self):
        event = StreamEvent(event="progress", data={"node": "collect_data"})
        assert event.event == "progress"
        assert event.data == {"node": "collect_data"}

    def test_rejects_invalid_event_type(self):
        with pytest.raises(Exception):
            StreamEvent(event="invalid_type", data={})

    @pytest.mark.parametrize("event_type", [
        "progress", "content", "tool_call", "status", "data", "error", "done",
    ])
    def test_all_event_types_accepted(self, event_type):
        event = StreamEvent(event=event_type, data={})
        assert event.event == event_type


class TestToSse:

    def test_sse_format_has_event_line_and_data_line(self):
        event = StreamEvent(event="progress", data={"node": "collect_data"})
        sse = event.to_sse()
        lines = sse.split("\n")
        assert lines[0] == "event: progress"
        assert lines[1].startswith("data: ")
        assert sse.endswith("\n\n")

    def test_sse_data_is_valid_json(self):
        event = progress_event(node="confirm", message="Preparing summary...")
        sse = event.to_sse()
        data_line = sse.split("\n")[1]
        payload = json.loads(data_line.removeprefix("data: "))
        assert payload["event"] == "progress"
        assert payload["data"]["node"] == "confirm"
        assert payload["data"]["message"] == "Preparing summary..."

    def test_sse_double_newline_terminator(self):
        event = done_event(status="completed")
        sse = event.to_sse()
        assert sse.endswith("\n\n")
        assert not sse.endswith("\n\n\n")


class TestFactoryFunctions:

    def test_progress_event(self):
        event = progress_event(node="collect_data", message="Understanding your needs...")
        assert event.event == "progress"
        assert event.data["node"] == "collect_data"
        assert event.data["message"] == "Understanding your needs..."
        assert event.data["phase"] == "update"
        assert event.data["label"] == ""

    def test_progress_event_defaults(self):
        event = progress_event(node="fetch_mcc")
        assert event.data["message"] == ""
        assert event.data["phase"] == "update"
        assert event.data["label"] == ""

    def test_progress_event_start_phase(self):
        event = progress_event(node="collect_data", phase="start", label="Collecting campaign details")
        assert event.data["phase"] == "start"
        assert event.data["label"] == "Collecting campaign details"
        assert event.data["message"] == ""

    def test_content_event(self):
        event = content_event(token="Hello", node="collect_data")
        assert event.event == "content"
        assert event.data["token"] == "Hello"
        assert event.data["node"] == "collect_data"

    def test_content_event_default_node(self):
        event = content_event(token="world")
        assert event.data["node"] == ""

    def test_tool_call_event(self):
        event = tool_call_event(
            name="update_ad_plan",
            args={"budget": "5000"},
            result={"saved": {"budget": "5000"}},
        )
        assert event.event == "tool_call"
        assert event.data["name"] == "update_ad_plan"
        assert event.data["args"] == {"budget": "5000"}
        assert event.data["result"]["saved"]["budget"] == "5000"

    def test_tool_call_event_default_result(self):
        event = tool_call_event(name="update_ad_plan", args={})
        assert event.data["result"] is None

    def test_status_event(self):
        event = status_event(status="selecting_mcc", progress="2/3", node="fetch_mcc")
        assert event.event == "status"
        assert event.data["status"] == "selecting_mcc"
        assert event.data["progress"] == "2/3"
        assert event.data["node"] == "fetch_mcc"

    def test_data_event(self):
        event = data_event(data_type="account_options", payload={"options": [{"id": "1"}]})
        assert event.event == "data"
        assert event.data["type"] == "account_options"
        assert event.data["payload"]["options"][0]["id"] == "1"

    def test_error_event(self):
        event = error_event(message="Something went wrong", code=502, recoverable=True)
        assert event.event == "error"
        assert event.data["message"] == "Something went wrong"
        assert event.data["code"] == 502
        assert event.data["recoverable"] is True

    def test_error_event_defaults(self):
        event = error_event(message="fail")
        assert event.data["code"] == 500
        assert event.data["recoverable"] is False

    def test_done_event_with_payload(self):
        event = done_event(status="completed", reply="Campaign created!", progress="3/3")
        assert event.event == "done"
        assert event.data["status"] == "completed"
        assert event.data["reply"] == "Campaign created!"
        assert event.data["progress"] == "3/3"

    def test_done_event_empty(self):
        event = done_event()
        assert event.event == "done"
        assert event.data == {}


class TestTransientFlag:
    """Verify transient defaults per event type."""

    def test_progress_is_transient(self):
        event = progress_event(node="scrape")
        assert event.transient is True

    def test_status_is_transient(self):
        event = status_event(status="running", progress="1/3")
        assert event.transient is True

    def test_content_is_persistent(self):
        event = content_event(token="Hello")
        assert event.transient is False

    def test_data_is_persistent(self):
        event = data_event(data_type="metadata", payload={"key": "val"})
        assert event.transient is False

    def test_error_is_persistent(self):
        event = error_event(message="fail")
        assert event.transient is False

    def test_done_is_persistent(self):
        event = done_event(status="completed")
        assert event.transient is False

    def test_tool_call_is_persistent(self):
        event = tool_call_event(name="fn", args={})
        assert event.transient is False


class TestReconciliationId:
    """Verify reconciliation id field on StreamEvent."""

    def test_default_id_is_none(self):
        event = progress_event(node="scrape")
        assert event.id is None

    def test_progress_accepts_id(self):
        event = progress_event(node="geo", id="geo-progress")
        assert event.id == "geo-progress"

    def test_status_accepts_id(self):
        event = status_event(status="running", progress="1/3", id="step-1")
        assert event.id == "step-1"

    def test_data_accepts_id(self):
        event = data_event("grid_progress", {"resolved": 10}, id="geo-progress")
        assert event.id == "geo-progress"

    def test_id_serialized_in_json(self):
        event = data_event("grid_progress", {"resolved": 10}, id="geo-progress")
        sse = event.to_sse()
        payload = json.loads(sse.split("\n")[1].removeprefix("data: "))
        assert payload["id"] == "geo-progress"

    def test_id_none_serialized_as_null(self):
        event = data_event("metadata", {"key": "val"})
        sse = event.to_sse()
        payload = json.loads(sse.split("\n")[1].removeprefix("data: "))
        assert payload["id"] is None


class TestSseRoundTrip:
    """Verify SSE serialization produces parseable events for an EventSource client."""

    def test_content_token_round_trip(self):
        original = content_event(token="Hello world", node="collect_data")
        sse = original.to_sse()

        event_line, data_line, *_ = sse.split("\n")
        assert event_line == "event: content"

        parsed = json.loads(data_line.removeprefix("data: "))
        restored = StreamEvent(**parsed)
        assert restored == original

    def test_error_event_round_trip(self):
        original = error_event(message="Timeout", code=504, recoverable=True)
        sse = original.to_sse()

        parsed = json.loads(sse.split("\n")[1].removeprefix("data: "))
        restored = StreamEvent(**parsed)
        assert restored == original

    def test_data_event_with_id_round_trip(self):
        original = data_event("grid_progress", {"resolved": 10}, id="geo-progress")
        sse = original.to_sse()

        parsed = json.loads(sse.split("\n")[1].removeprefix("data: "))
        restored = StreamEvent(**parsed)
        assert restored == original
        assert restored.id == "geo-progress"
        assert restored.transient is False

    def test_transient_progress_round_trip(self):
        original = progress_event(node="scrape", message="Scraping...", id="scrape-1")
        sse = original.to_sse()

        parsed = json.loads(sse.split("\n")[1].removeprefix("data: "))
        restored = StreamEvent(**parsed)
        assert restored == original
        assert restored.transient is True
        assert restored.id == "scrape-1"
