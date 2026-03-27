"""Tests for core.streaming.langgraph_translator — maps stream_mode chunks to StreamEvents."""

from types import SimpleNamespace

from core.streaming.langgraph_translator import translate_stream_chunk


class TestCustomEvents:
    """Test translate_stream_chunk("custom", ...) — events from get_stream_writer()."""

    def test_progress_event_update(self):
        data = {"type": "progress", "node": "collect_data", "content": "Interpreting 12k as budget"}
        events = translate_stream_chunk("custom", data)
        assert len(events) == 1
        assert events[0].event == "progress"
        assert events[0].data["node"] == "collect_data"
        assert events[0].data["message"] == "Interpreting 12k as budget"
        assert events[0].data["phase"] == "update"
        assert events[0].data["label"] == ""

    def test_progress_event_start_with_label(self):
        data = {"type": "progress", "node": "collect_data", "phase": "start", "label": "Collecting campaign details"}
        events = translate_stream_chunk("custom", data)
        assert len(events) == 1
        assert events[0].data["phase"] == "start"
        assert events[0].data["label"] == "Collecting campaign details"
        assert events[0].data["message"] == ""

    def test_field_update_event(self):
        data = {"type": "field_update", "field": "budget", "value": "12000", "status": "valid"}
        events = translate_stream_chunk("custom", data)
        assert len(events) == 1
        assert events[0].event == "data"
        assert events[0].data["type"] == "field_update"
        assert events[0].data["payload"]["field"] == "budget"
        assert events[0].data["payload"]["value"] == "12000"
        assert events[0].data["payload"]["status"] == "valid"

    def test_field_update_with_error(self):
        data = {"type": "field_update", "field": "websiteURL", "value": "bad", "status": "invalid", "error": "Invalid URL"}
        events = translate_stream_chunk("custom", data)
        assert events[0].data["payload"]["error"] == "Invalid URL"

    def test_status_event(self):
        data = {"type": "status", "status": "selecting_mcc", "progress": "2/3", "node": "collect_data"}
        events = translate_stream_chunk("custom", data)
        assert len(events) == 1
        assert events[0].event == "status"
        assert events[0].data["status"] == "selecting_mcc"
        assert events[0].data["progress"] == "2/3"

    def test_tool_call_event(self):
        data = {"type": "tool_call", "name": "update_ad_plan", "args": {"budget": "5000"}}
        events = translate_stream_chunk("custom", data)
        assert len(events) == 1
        assert events[0].event == "tool_call"
        assert events[0].data["name"] == "update_ad_plan"

    def test_unknown_custom_type_ignored(self):
        data = {"type": "something_else", "content": "whatever"}
        events = translate_stream_chunk("custom", data)
        assert events == []

    def test_empty_custom_data_ignored(self):
        events = translate_stream_chunk("custom", {})
        assert events == []


class TestMessageChunks:
    """Test translate_stream_chunk("messages", ...) — (AIMessageChunk, metadata) tuples."""

    def test_content_token_extracted(self):
        chunk = SimpleNamespace(content="Hello")
        metadata = {"langgraph_node": "collect_data"}
        events = translate_stream_chunk("messages", (chunk, metadata))
        assert len(events) == 1
        assert events[0].event == "content"
        assert events[0].data["token"] == "Hello"
        assert events[0].data["node"] == "collect_data"

    def test_empty_content_ignored(self):
        chunk = SimpleNamespace(content="")
        events = translate_stream_chunk("messages", (chunk, {}))
        assert events == []

    def test_no_content_attr_ignored(self):
        chunk = SimpleNamespace()
        events = translate_stream_chunk("messages", (chunk, {}))
        assert events == []


class TestUnknownModes:
    """Test that unknown stream modes are gracefully ignored."""

    def test_values_mode_returns_empty(self):
        events = translate_stream_chunk("values", {"status": "in_progress"})
        assert events == []

    def test_unknown_mode_returns_empty(self):
        events = translate_stream_chunk("debug", {"data": "something"})
        assert events == []
