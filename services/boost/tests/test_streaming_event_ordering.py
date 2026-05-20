"""Integration tests verifying the exact ordering of Anthropic streaming events.

These tests exercise the full streaming path through _anthropic_stream_converter
for complex multi-block scenarios, asserting the precise sequence of event types
produced by the converter — not just that certain events are present, but that
they appear in the correct order with the correct indices and delta types.
"""

import json
import pytest

from helpers import (
    FakeLLM,
    make_anthropic_app,
    make_client,
    parse_anthropic_sse_events,
    setup_mock_llm,
    sse_chunk,
    ANTHROPIC_BODY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event_summary(event):
    """Return a (type, delta_type_or_none, index_or_none) tuple for an event."""
    etype = event.get("type")
    idx = event.get("index")
    delta = event.get("delta", {})
    delta_type = delta.get("type") if isinstance(delta, dict) else None
    # message_start / message_delta / message_stop carry no index
    if etype in ("message_start", "message_delta", "message_stop"):
        return (etype, None, None)
    # content_block_start has content_block.type
    if etype == "content_block_start":
        cb_type = event.get("content_block", {}).get("type")
        return (etype, cb_type, idx)
    # content_block_delta
    if etype == "content_block_delta":
        return (etype, delta_type, idx)
    # content_block_stop
    if etype == "content_block_stop":
        return (etype, None, idx)
    return (etype, None, None)


def _extract_event_types(events):
    """Return just the top-level event types as a list."""
    return [e["type"] for e in events]


def _make_stream_body(stream=True, **overrides):
    """Build a streaming Anthropic request body."""
    body = {**ANTHROPIC_BODY, "stream": stream}
    body.update(overrides)
    return body


def _reasoning_chunk(text, finish=False):
    """Build a chunk with reasoning_content delta."""
    delta = {"reasoning_content": text}
    choice = {"delta": delta, "index": 0}
    if finish:
        choice["finish_reason"] = "stop"
    return sse_chunk({"choices": [choice]})


def _text_chunk(text, finish=False, finish_reason="stop"):
    """Build a chunk with text content delta."""
    delta = {"content": text}
    choice = {"delta": delta, "index": 0}
    if finish:
        choice["finish_reason"] = finish_reason
    return sse_chunk({"choices": [choice]})


def _tool_chunk(tool_id=None, name=None, args=None, index=0, finish=False):
    """Build a chunk with a tool call delta."""
    tc = {"index": index}
    func = {}
    if tool_id:
        tc["id"] = tool_id
    if name:
        func["name"] = name
    if args:
        func["arguments"] = args
    if func:
        tc["function"] = func
    delta = {"tool_calls": [tc]}
    choice = {"delta": delta, "index": 0}
    if finish:
        choice["finish_reason"] = "tool_calls"
    return sse_chunk({"choices": [choice]})


def _finish_chunk(finish_reason="stop", prompt_tokens=10, completion_tokens=5):
    """Build a finish-only chunk with usage."""
    return sse_chunk({
        "choices": [{"delta": {}, "finish_reason": finish_reason, "index": 0}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    })


def _done():
    return "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    return make_anthropic_app()


class TestThinkingThenText:
    """Scenario (a): thinking_start -> thinking_deltas -> signature_delta ->
    thinking_stop -> text_start -> text_deltas -> text_stop -> message_delta
    -> message_stop."""

    def test_full_sequence(self, monkeypatch, app):
        chunks = [
            _reasoning_chunk("Let me think"),
            _reasoning_chunk(" about this"),
            _text_chunk("The answer"),
            _text_chunk(" is 42"),
            _finish_chunk("stop"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        assert resp.status_code == 200

        events = parse_anthropic_sse_events(resp.text)
        summaries = [_event_summary(e) for e in events]

        expected = [
            # Envelope open
            ("message_start", None, None),
            # Thinking block (index 0)
            ("content_block_start", "thinking", 0),
            ("content_block_delta", "thinking_delta", 0),
            ("content_block_delta", "thinking_delta", 0),
            # Close thinking: signature_delta then stop
            ("content_block_delta", "signature_delta", 0),
            ("content_block_stop", None, 0),
            # Text block (index 1)
            ("content_block_start", "text", 1),
            ("content_block_delta", "text_delta", 1),
            ("content_block_delta", "text_delta", 1),
            ("content_block_stop", None, 1),
            # Envelope close
            ("message_delta", None, None),
            ("message_stop", None, None),
        ]

        assert summaries == expected

    def test_message_delta_contains_stop_reason(self, monkeypatch, app):
        chunks = [
            _reasoning_chunk("think"),
            _text_chunk("answer"),
            _finish_chunk("stop"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        msg_delta = [e for e in events if e["type"] == "message_delta"][0]
        assert msg_delta["delta"]["stop_reason"] == "end_turn"

    def test_indices_are_monotonic(self, monkeypatch, app):
        chunks = [
            _reasoning_chunk("think"),
            _text_chunk("text"),
            _finish_chunk(),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        indices = [
            e.get("index") for e in events
            if e["type"] in ("content_block_start", "content_block_stop")
        ]
        # thinking block at 0, text block at 1
        assert indices == [0, 0, 1, 1]


class TestThinkingThenToolUse:
    """Scenario (b): thinking -> text (if any) -> tool_use_start ->
    input_json_deltas -> tool_use_stop -> message_delta(tool_use)."""

    def test_thinking_text_then_tool(self, monkeypatch, app):
        chunks = [
            _reasoning_chunk("I should use a tool"),
            _text_chunk("Looking up..."),
            _tool_chunk(tool_id="call_abc", name="search", args='{"q":'),
            _tool_chunk(args='"hello"}', index=0),
            _finish_chunk("tool_calls"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        summaries = [_event_summary(e) for e in events]

        expected = [
            ("message_start", None, None),
            # Thinking (index 0)
            ("content_block_start", "thinking", 0),
            ("content_block_delta", "thinking_delta", 0),
            ("content_block_delta", "signature_delta", 0),
            ("content_block_stop", None, 0),
            # Text (index 1)
            ("content_block_start", "text", 1),
            ("content_block_delta", "text_delta", 1),
            ("content_block_stop", None, 1),
            # Tool use (index 2)
            ("content_block_start", "tool_use", 2),
            ("content_block_delta", "input_json_delta", 2),
            ("content_block_delta", "input_json_delta", 2),
            ("content_block_stop", None, 2),
            # Envelope close with tool_use stop reason
            ("message_delta", None, None),
            ("message_stop", None, None),
        ]

        assert summaries == expected

        # Verify stop reason
        msg_delta = [e for e in events if e["type"] == "message_delta"][0]
        assert msg_delta["delta"]["stop_reason"] == "tool_use"

    def test_thinking_directly_to_tool_no_text(self, monkeypatch, app):
        """Thinking followed by tool use with no intermediate text."""
        chunks = [
            _reasoning_chunk("use tool"),
            _tool_chunk(tool_id="call_xyz", name="get_weather", args='{"city":"NYC"}'),
            _finish_chunk("tool_calls"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        summaries = [_event_summary(e) for e in events]

        expected = [
            ("message_start", None, None),
            # Thinking (index 0)
            ("content_block_start", "thinking", 0),
            ("content_block_delta", "thinking_delta", 0),
            # Tool opens: thinking closes first (signature + stop)
            ("content_block_delta", "signature_delta", 0),
            ("content_block_stop", None, 0),
            # Tool use (index 1)
            ("content_block_start", "tool_use", 1),
            ("content_block_delta", "input_json_delta", 1),
            ("content_block_stop", None, 1),
            ("message_delta", None, None),
            ("message_stop", None, None),
        ]

        assert summaries == expected


class TestMultipleTools:
    """Scenario (c): text -> tool1_start -> tool1_deltas -> tool1_stop ->
    tool2_start -> tool2_deltas -> tool2_stop -> message_delta(tool_use)."""

    def test_text_then_two_tools(self, monkeypatch, app):
        chunks = [
            _text_chunk("I'll search and calculate."),
            # Tool 1
            _tool_chunk(tool_id="call_1", name="search", args='{"q":"pi"}', index=0),
            # Tool 2
            _tool_chunk(tool_id="call_2", name="calculate", args='{"expr":', index=1),
            _tool_chunk(args='"3.14*2"}', index=1),
            _finish_chunk("tool_calls"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        summaries = [_event_summary(e) for e in events]

        expected = [
            ("message_start", None, None),
            # Text (index 0)
            ("content_block_start", "text", 0),
            ("content_block_delta", "text_delta", 0),
            # Text closed when first tool opens
            ("content_block_stop", None, 0),
            # Tool 1 (index 1)
            ("content_block_start", "tool_use", 1),
            ("content_block_delta", "input_json_delta", 1),
            # Tool 2 (index 2)
            ("content_block_start", "tool_use", 2),
            ("content_block_delta", "input_json_delta", 2),
            ("content_block_delta", "input_json_delta", 2),
            # Stops for both tools
            ("content_block_stop", None, 1),
            ("content_block_stop", None, 2),
            ("message_delta", None, None),
            ("message_stop", None, None),
        ]

        assert summaries == expected

        msg_delta = [e for e in events if e["type"] == "message_delta"][0]
        assert msg_delta["delta"]["stop_reason"] == "tool_use"

    def test_three_tools_no_text(self, monkeypatch, app):
        """Three consecutive tools with no preceding text."""
        chunks = [
            _tool_chunk(tool_id="call_a", name="tool_a", args='{}', index=0),
            _tool_chunk(tool_id="call_b", name="tool_b", args='{"x":1}', index=1),
            _tool_chunk(tool_id="call_c", name="tool_c", args='{"y":2}', index=2),
            _finish_chunk("tool_calls"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        summaries = [_event_summary(e) for e in events]

        expected = [
            ("message_start", None, None),
            # Tool a (index 0)
            ("content_block_start", "tool_use", 0),
            ("content_block_delta", "input_json_delta", 0),
            # Tool b (index 1)
            ("content_block_start", "tool_use", 1),
            ("content_block_delta", "input_json_delta", 1),
            # Tool c (index 2)
            ("content_block_start", "tool_use", 2),
            ("content_block_delta", "input_json_delta", 2),
            # Stops for all three
            ("content_block_stop", None, 0),
            ("content_block_stop", None, 1),
            ("content_block_stop", None, 2),
            ("message_delta", None, None),
            ("message_stop", None, None),
        ]

        assert summaries == expected

    def test_tool_indices_are_unique(self, monkeypatch, app):
        """Each tool block must get a unique sequential index."""
        chunks = [
            _tool_chunk(tool_id="call_1", name="a", args='{}', index=0),
            _tool_chunk(tool_id="call_2", name="b", args='{}', index=1),
            _finish_chunk("tool_calls"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        start_indices = [
            e["index"] for e in events
            if e["type"] == "content_block_start"
        ]
        assert start_indices == [0, 1]
        assert len(set(start_indices)) == len(start_indices)


class TestTextAfterTools:
    """Scenario (d): tool -> text (verify new text block opens after tool)."""

    def test_tool_then_text(self, monkeypatch, app):
        """After a tool block completes, text should open a new block."""
        # Simulate: tool call first, then text appears after
        # The tool arrives and gets emitted. Then text arrives.
        chunks = [
            _tool_chunk(tool_id="call_1", name="search", args='{"q":"test"}', index=0),
            _text_chunk("Here is the result."),
            _finish_chunk("stop"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        summaries = [_event_summary(e) for e in events]

        # The text block should have a higher index than the tool block
        expected = [
            ("message_start", None, None),
            # Tool (index 0)
            ("content_block_start", "tool_use", 0),
            ("content_block_delta", "input_json_delta", 0),
            # Text arrives — text block opens at index 1
            ("content_block_start", "text", 1),
            ("content_block_delta", "text_delta", 1),
            # Close text, then close tool
            ("content_block_stop", None, 1),
            ("content_block_stop", None, 0),
            ("message_delta", None, None),
            ("message_stop", None, None),
        ]

        assert summaries == expected

    def test_text_tool_text_sandwich(self, monkeypatch, app):
        """Text -> tool -> more text. The second text should get a new block."""
        chunks = [
            _text_chunk("Before tool. "),
            _tool_chunk(tool_id="call_1", name="calc", args='{"x":1}', index=0),
            _text_chunk("After tool."),
            _finish_chunk("stop"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        summaries = [_event_summary(e) for e in events]

        expected = [
            ("message_start", None, None),
            # First text (index 0)
            ("content_block_start", "text", 0),
            ("content_block_delta", "text_delta", 0),
            # Tool closes text, opens tool (index 1)
            ("content_block_stop", None, 0),
            ("content_block_start", "tool_use", 1),
            ("content_block_delta", "input_json_delta", 1),
            # Second text opens new block (index 2)
            ("content_block_start", "text", 2),
            ("content_block_delta", "text_delta", 2),
            # Close open blocks
            ("content_block_stop", None, 2),
            ("content_block_stop", None, 1),
            ("message_delta", None, None),
            ("message_stop", None, None),
        ]

        assert summaries == expected

        # Verify the two text blocks have different indices
        text_starts = [
            e for e in events
            if e["type"] == "content_block_start"
            and e["content_block"]["type"] == "text"
        ]
        assert len(text_starts) == 2
        assert text_starts[0]["index"] != text_starts[1]["index"]


class TestEmptyThinkingBlock:
    """Scenario (e): thinking_start -> signature_delta -> thinking_stop
    (no thinking_delta)."""

    def test_thinking_with_no_thinking_content(self, monkeypatch, app):
        """When reasoning is present but transitions directly to text,
        the thinking block should still get signature_delta + stop."""
        # This happens when the first chunk has reasoning, then the
        # very next chunk has text — so there's only one thinking delta.
        # But for truly empty thinking, we need thinking block opened
        # and then immediately closed. Since the converter opens thinking
        # on any reasoning_content, the minimal case is reasoning=""
        # which is falsy and doesn't open a block. So the "empty thinking"
        # case is: open thinking with minimal content, then text closes it.
        chunks = [
            _reasoning_chunk(" "),  # minimal non-empty reasoning
            _text_chunk("Result"),
            _finish_chunk(),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        summaries = [_event_summary(e) for e in events]

        expected = [
            ("message_start", None, None),
            # Thinking block opens with minimal content
            ("content_block_start", "thinking", 0),
            ("content_block_delta", "thinking_delta", 0),
            # Text arrives: close thinking with signature + stop
            ("content_block_delta", "signature_delta", 0),
            ("content_block_stop", None, 0),
            # Text block
            ("content_block_start", "text", 1),
            ("content_block_delta", "text_delta", 1),
            ("content_block_stop", None, 1),
            ("message_delta", None, None),
            ("message_stop", None, None),
        ]

        assert summaries == expected

    def test_thinking_only_no_text(self, monkeypatch, app):
        """Thinking block with no subsequent text — still gets proper closure."""
        chunks = [
            _reasoning_chunk("some thought"),
            _finish_chunk(),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        summaries = [_event_summary(e) for e in events]

        # Thinking block should be opened, get its delta, then closed
        # with signature_delta + stop at the end (post-loop cleanup)
        expected = [
            ("message_start", None, None),
            ("content_block_start", "thinking", 0),
            ("content_block_delta", "thinking_delta", 0),
            ("content_block_delta", "signature_delta", 0),
            ("content_block_stop", None, 0),
            ("message_delta", None, None),
            ("message_stop", None, None),
        ]

        assert summaries == expected


class TestStopSequence:
    """Scenario (f): text -> text_stop -> message_delta(stop_sequence, stop_text)."""

    def test_stop_sequence_in_content(self, monkeypatch, app):
        """When stop_sequences are configured and content ends with one,
        message_delta should report stop_sequence stop reason."""
        chunks = [
            _text_chunk("Hello world"),
            _text_chunk("STOP_HERE"),
            _finish_chunk("stop"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        body = _make_stream_body(stop_sequences=["STOP_HERE"])
        resp = client.post(
            "/v1/messages",
            json=body,
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        summaries = [_event_summary(e) for e in events]

        expected = [
            ("message_start", None, None),
            ("content_block_start", "text", 0),
            ("content_block_delta", "text_delta", 0),
            ("content_block_delta", "text_delta", 0),
            ("content_block_stop", None, 0),
            ("message_delta", None, None),
            ("message_stop", None, None),
        ]

        assert summaries == expected

        msg_delta = [e for e in events if e["type"] == "message_delta"][0]
        assert msg_delta["delta"]["stop_reason"] == "stop_sequence"
        assert msg_delta["delta"]["stop_sequence"] == "STOP_HERE"

    def test_stop_sequence_not_matching_defaults_to_first(self, monkeypatch, app):
        """When stop_sequences are configured but content doesn't end with any,
        the default behavior uses the first stop sequence."""
        chunks = [
            _text_chunk("Some output"),
            _finish_chunk("stop"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        body = _make_stream_body(stop_sequences=["###", "---"])
        resp = client.post(
            "/v1/messages",
            json=body,
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        msg_delta = [e for e in events if e["type"] == "message_delta"][0]
        assert msg_delta["delta"]["stop_reason"] == "stop_sequence"
        assert msg_delta["delta"]["stop_sequence"] == "###"

    def test_no_stop_sequences_gives_end_turn(self, monkeypatch, app):
        """Without stop_sequences, finish_reason=stop maps to end_turn."""
        chunks = [
            _text_chunk("Hello"),
            _finish_chunk("stop"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        msg_delta = [e for e in events if e["type"] == "message_delta"][0]
        assert msg_delta["delta"]["stop_reason"] == "end_turn"
        assert msg_delta["delta"]["stop_sequence"] is None


class TestMaxTokensStop:
    """finish_reason=length should produce stop_reason=max_tokens."""

    def test_length_maps_to_max_tokens(self, monkeypatch, app):
        chunks = [
            _text_chunk("Truncated output"),
            _finish_chunk("length"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        msg_delta = [e for e in events if e["type"] == "message_delta"][0]
        assert msg_delta["delta"]["stop_reason"] == "max_tokens"
        assert msg_delta["delta"]["stop_sequence"] is None


class TestFullThinkingTextToolSequence:
    """Combined scenario: thinking -> text -> multiple tools."""

    def test_thinking_text_two_tools(self, monkeypatch, app):
        chunks = [
            # Thinking
            _reasoning_chunk("Let me analyze"),
            _reasoning_chunk(" this problem"),
            # Text
            _text_chunk("I'll use two tools."),
            # Tool 1
            _tool_chunk(tool_id="call_1", name="search", args='{"q":"a"}', index=0),
            # Tool 2
            _tool_chunk(tool_id="call_2", name="calc", args='{"x":1}', index=1),
            _finish_chunk("tool_calls"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        summaries = [_event_summary(e) for e in events]

        expected = [
            ("message_start", None, None),
            # Thinking (index 0)
            ("content_block_start", "thinking", 0),
            ("content_block_delta", "thinking_delta", 0),
            ("content_block_delta", "thinking_delta", 0),
            # First text closes thinking
            ("content_block_delta", "signature_delta", 0),
            ("content_block_stop", None, 0),
            # Text (index 1)
            ("content_block_start", "text", 1),
            ("content_block_delta", "text_delta", 1),
            # Tool 1 closes text
            ("content_block_stop", None, 1),
            # Tool 1 (index 2)
            ("content_block_start", "tool_use", 2),
            ("content_block_delta", "input_json_delta", 2),
            # Tool 2 (index 3)
            ("content_block_start", "tool_use", 3),
            ("content_block_delta", "input_json_delta", 3),
            # Close tools
            ("content_block_stop", None, 2),
            ("content_block_stop", None, 3),
            ("message_delta", None, None),
            ("message_stop", None, None),
        ]

        assert summaries == expected

        msg_delta = [e for e in events if e["type"] == "message_delta"][0]
        assert msg_delta["delta"]["stop_reason"] == "tool_use"


class TestEnvelopeIntegrity:
    """Verify the stream always starts with message_start and ends with
    message_stop, regardless of content."""

    def test_text_only_envelope(self, monkeypatch, app):
        chunks = [_text_chunk("hi"), _finish_chunk(), _done()]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        types = _extract_event_types(events)
        assert types[0] == "message_start"
        assert types[-1] == "message_stop"
        assert types[-2] == "message_delta"

    def test_empty_stream_envelope(self, monkeypatch, app):
        """Even an empty stream (finish only) should produce a valid envelope."""
        chunks = [_finish_chunk(), _done()]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        types = _extract_event_types(events)
        assert types[0] == "message_start"
        assert types[-1] == "message_stop"
        assert types[-2] == "message_delta"
        # No content blocks at all
        assert "content_block_start" not in types
        assert "content_block_stop" not in types

    def test_tool_only_envelope(self, monkeypatch, app):
        chunks = [
            _tool_chunk(tool_id="call_1", name="f", args='{}', index=0),
            _finish_chunk("tool_calls"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        types = _extract_event_types(events)
        assert types[0] == "message_start"
        assert types[-1] == "message_stop"
        assert types[-2] == "message_delta"


class TestBlockStartStopPairing:
    """Every content_block_start must have a matching content_block_stop
    with the same index."""

    def _get_start_stop_indices(self, events):
        starts = [
            e["index"] for e in events if e["type"] == "content_block_start"
        ]
        stops = [
            e["index"] for e in events if e["type"] == "content_block_stop"
        ]
        return starts, stops

    def test_text_only_pairing(self, monkeypatch, app):
        chunks = [_text_chunk("a"), _text_chunk("b"), _finish_chunk(), _done()]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        starts, stops = self._get_start_stop_indices(events)
        assert sorted(starts) == sorted(stops)

    def test_thinking_text_tool_pairing(self, monkeypatch, app):
        chunks = [
            _reasoning_chunk("think"),
            _text_chunk("text"),
            _tool_chunk(tool_id="call_1", name="f", args='{}', index=0),
            _finish_chunk("tool_calls"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        starts, stops = self._get_start_stop_indices(events)
        assert sorted(starts) == sorted(stops)
        # 3 blocks: thinking, text, tool
        assert len(starts) == 3

    def test_text_two_tools_text_pairing(self, monkeypatch, app):
        chunks = [
            _text_chunk("a"),
            _tool_chunk(tool_id="call_1", name="f1", args='{}', index=0),
            _tool_chunk(tool_id="call_2", name="f2", args='{}', index=1),
            _text_chunk("b"),
            _finish_chunk(),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        starts, stops = self._get_start_stop_indices(events)
        assert sorted(starts) == sorted(stops)
        # 4 blocks: text, tool1, tool2, text
        assert len(starts) == 4


class TestDeltaTypesCorrectness:
    """Verify delta types match their parent content block types."""

    def test_thinking_block_only_gets_thinking_deltas(self, monkeypatch, app):
        chunks = [
            _reasoning_chunk("a"),
            _reasoning_chunk("b"),
            _text_chunk("c"),
            _finish_chunk(),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)

        # Find the thinking block index
        thinking_start = [
            e for e in events
            if e["type"] == "content_block_start"
            and e["content_block"]["type"] == "thinking"
        ]
        assert len(thinking_start) == 1
        thinking_idx = thinking_start[0]["index"]

        # All deltas at thinking_idx should be thinking_delta or signature_delta
        thinking_deltas = [
            e for e in events
            if e["type"] == "content_block_delta"
            and e["index"] == thinking_idx
        ]
        delta_types = [e["delta"]["type"] for e in thinking_deltas]
        assert all(dt in ("thinking_delta", "signature_delta") for dt in delta_types)

    def test_text_block_only_gets_text_deltas(self, monkeypatch, app):
        chunks = [
            _text_chunk("hello"),
            _text_chunk(" world"),
            _finish_chunk(),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)

        text_start = [
            e for e in events
            if e["type"] == "content_block_start"
            and e["content_block"]["type"] == "text"
        ]
        assert len(text_start) == 1
        text_idx = text_start[0]["index"]

        text_deltas = [
            e for e in events
            if e["type"] == "content_block_delta"
            and e["index"] == text_idx
        ]
        delta_types = [e["delta"]["type"] for e in text_deltas]
        assert all(dt == "text_delta" for dt in delta_types)

    def test_tool_block_only_gets_input_json_deltas(self, monkeypatch, app):
        chunks = [
            _tool_chunk(tool_id="call_1", name="f", args='{"a":', index=0),
            _tool_chunk(args='"b"}', index=0),
            _finish_chunk("tool_calls"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)

        tool_start = [
            e for e in events
            if e["type"] == "content_block_start"
            and e["content_block"]["type"] == "tool_use"
        ]
        assert len(tool_start) == 1
        tool_idx = tool_start[0]["index"]

        tool_deltas = [
            e for e in events
            if e["type"] == "content_block_delta"
            and e["index"] == tool_idx
        ]
        delta_types = [e["delta"]["type"] for e in tool_deltas]
        assert all(dt == "input_json_delta" for dt in delta_types)


class TestUsageInMessageDelta:
    """Verify usage tokens appear in the final message_delta event."""

    def test_usage_tokens_forwarded(self, monkeypatch, app):
        chunks = [
            _text_chunk("hi"),
            _finish_chunk("stop", prompt_tokens=42, completion_tokens=7),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        msg_delta = [e for e in events if e["type"] == "message_delta"][0]
        assert msg_delta["usage"]["input_tokens"] == 42
        assert msg_delta["usage"]["output_tokens"] == 7

    def test_usage_includes_cache_fields(self, monkeypatch, app):
        chunks = [_text_chunk("x"), _finish_chunk(), _done()]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        msg_delta = [e for e in events if e["type"] == "message_delta"][0]
        assert "cache_creation_input_tokens" in msg_delta["usage"]
        assert "cache_read_input_tokens" in msg_delta["usage"]


class TestMessageStartShape:
    """Verify the message_start event has the required shape."""

    def test_message_start_fields(self, monkeypatch, app):
        chunks = [_text_chunk("x"), _finish_chunk(), _done()]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        msg_start = events[0]
        assert msg_start["type"] == "message_start"
        msg = msg_start["message"]
        assert msg["type"] == "message"
        assert msg["role"] == "assistant"
        assert msg["model"] == "claude-test"
        assert msg["content"] == []
        assert msg["stop_reason"] is None
        assert msg["stop_sequence"] is None
        assert "input_tokens" in msg["usage"]
        assert "output_tokens" in msg["usage"]

    def test_model_echoed_from_request(self, monkeypatch, app):
        chunks = [_text_chunk("x"), _finish_chunk(), _done()]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        body = _make_stream_body()
        body["model"] = "my-custom-model"
        resp = client.post(
            "/v1/messages",
            json=body,
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        assert events[0]["message"]["model"] == "my-custom-model"


class TestToolUseBlockContent:
    """Verify tool use content_block_start has the right shape."""

    def test_tool_use_start_shape(self, monkeypatch, app):
        chunks = [
            _tool_chunk(tool_id="call_abc", name="get_weather", args='{"city":"NYC"}', index=0),
            _finish_chunk("tool_calls"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        tool_start = [
            e for e in events
            if e["type"] == "content_block_start"
            and e["content_block"]["type"] == "tool_use"
        ][0]
        cb = tool_start["content_block"]
        assert cb["type"] == "tool_use"
        assert cb["id"].startswith("toolu_")
        assert cb["name"] == "get_weather"
        assert cb["input"] == {}

    def test_tool_args_accumulated(self, monkeypatch, app):
        """Tool arguments arrive across multiple chunks and are all emitted."""
        chunks = [
            _tool_chunk(tool_id="call_1", name="f", args='{"a":', index=0),
            _tool_chunk(args=' "b",', index=0),
            _tool_chunk(args=' "c": 1}', index=0),
            _finish_chunk("tool_calls"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)
        json_deltas = [
            e["delta"]["partial_json"]
            for e in events
            if e["type"] == "content_block_delta"
            and e["delta"]["type"] == "input_json_delta"
        ]
        # First emission includes accumulated args from before ID was known
        combined = "".join(json_deltas)
        assert combined == '{"a": "b", "c": 1}'


class TestContentBlockStartBeforeDeltas:
    """No content_block_delta should appear before its content_block_start."""

    def test_delta_never_before_start(self, monkeypatch, app):
        chunks = [
            _reasoning_chunk("think"),
            _text_chunk("text"),
            _tool_chunk(tool_id="call_1", name="f", args='{}', index=0),
            _finish_chunk("tool_calls"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)

        started_indices = set()
        for e in events:
            if e["type"] == "content_block_start":
                started_indices.add(e["index"])
            elif e["type"] == "content_block_delta":
                assert e["index"] in started_indices, (
                    f"Delta at index {e['index']} before its start event"
                )

    def test_stop_never_before_start(self, monkeypatch, app):
        """content_block_stop should never come before content_block_start."""
        chunks = [
            _text_chunk("a"),
            _tool_chunk(tool_id="call_1", name="f", args='{}', index=0),
            _tool_chunk(tool_id="call_2", name="g", args='{}', index=1),
            _finish_chunk("tool_calls"),
            _done(),
        ]
        llm = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, llm)
        client = make_client(app)

        resp = client.post(
            "/v1/messages",
            json=_make_stream_body(),
            headers={"x-api-key": "test"},
        )
        events = parse_anthropic_sse_events(resp.text)

        started_indices = set()
        for e in events:
            if e["type"] == "content_block_start":
                started_indices.add(e["index"])
            elif e["type"] == "content_block_stop":
                assert e["index"] in started_indices, (
                    f"Stop at index {e['index']} before its start event"
                )
