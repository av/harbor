"""Comprehensive Pydantic model validation for all Anthropic compat SSE events.

Every SSE event our Anthropic compat layer produces is constructed by hand as
a dict and fed to the corresponding Anthropic SDK Pydantic model's
``model_validate`` method.  If any required field is missing, the wrong type,
or mis-named, the test fails -- catching SDK incompatibilities at unit-test
time rather than at runtime with a real client.

Covered event paths:
  - Text-only response (message_start, ping, content_block_start[text],
    content_block_delta[text_delta], content_block_stop, message_delta,
    message_stop)
  - Tool call response (content_block_start[tool_use],
    content_block_delta[input_json_delta], content_block_stop)
  - Thinking response (content_block_start[thinking],
    content_block_delta[thinking_delta], content_block_delta[signature_delta],
    content_block_stop)
  - Mixed response (thinking + text + tool_use)
  - Empty response (no content blocks)
  - Non-streaming Message model validation
"""

import json
import sys
import os
import asyncio

import pytest

import anthropic.types as sdk

# Ensure src dir is on the path (conftest.py handles this, but be explicit)
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import anthropic_compat
from helpers import FakeLLM, sse_chunk, openai_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_sse_events(raw_text):
    """Parse raw SSE text into (event_type, data_dict) pairs.

    Skips standalone retry: lines and keep-alive comments.
    """
    events = []
    for block in raw_text.strip().split("\n\n"):
        event_type = None
        data_str = None
        for line in block.strip().split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
        if event_type and data_str:
            events.append((event_type, json.loads(data_str)))
    return events


# Map from our SSE event type names to SDK Pydantic models.
EVENT_MODEL_MAP = {
    "message_start": sdk.RawMessageStartEvent,
    "content_block_start": sdk.RawContentBlockStartEvent,
    "content_block_delta": sdk.RawContentBlockDeltaEvent,
    "content_block_stop": sdk.RawContentBlockStopEvent,
    "message_delta": sdk.RawMessageDeltaEvent,
    "message_stop": sdk.RawMessageStopEvent,
    # ping events have no SDK model in the pinned SDK; validate manually.
}


def _validate_event(event_type, data):
    """Validate a single SSE event dict against the corresponding Pydantic model.

    Returns the validated model instance, or raises on failure.
    Ping events are validated manually because the pinned SDK has no model.
    """
    if event_type == "ping":
        assert data == {"type": "ping"}
        return data
    if event_type == "error":
        return sdk.ErrorResponse.model_validate(data)
    model_cls = EVENT_MODEL_MAP.get(event_type)
    if model_cls is None:
        pytest.fail(f"Unknown event type: {event_type}")
    return model_cls.model_validate(data)


def _validate_all_events(events):
    """Validate every event in a list of (event_type, data) pairs.

    Returns a list of (event_type, validated_model) pairs.
    Ping events are checked manually.
    """
    validated = []
    for event_type, data in events:
        model = _validate_event(event_type, data)
        if model is not None:
            validated.append((event_type, model))
    return validated


async def _run_stream_converter(chunks, request_model="test-model",
                                stop_sequences=None):
    """Run the Anthropic streaming converter with mock chunks and collect output."""
    async def _fake_stream():
        for chunk in chunks:
            yield chunk

    raw_output = []
    async for sse_str in anthropic_compat._anthropic_stream_converter(
        _fake_stream(), request_model, stop_sequences
    ):
        raw_output.append(sse_str)

    # Join all output and parse events
    full_text = "".join(raw_output)
    return _parse_sse_events(full_text)


# ---------------------------------------------------------------------------
# Text-only response path
# ---------------------------------------------------------------------------

class TestTextOnlyStreamValidation:
    """Validate all events in a text-only streaming response."""

    @pytest.mark.asyncio
    async def test_all_text_events_validate(self):
        """A simple text stream produces events that all pass Pydantic validation."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"role": "assistant", "content": "Hello"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": " world"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)

        types = [et for et, _ in validated]
        assert "message_start" in types
        assert "content_block_start" in types
        assert "content_block_delta" in types
        assert "content_block_stop" in types
        assert "message_delta" in types
        assert "message_stop" in types

    @pytest.mark.asyncio
    async def test_message_start_has_valid_message(self):
        """The message_start event carries a valid Message object."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "Hi"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        msg_start = [d for t, d in events if t == "message_start"]
        assert len(msg_start) == 1

        evt = _validate_event("message_start", msg_start[0])
        assert evt.type == "message_start"
        assert evt.message.role == "assistant"
        assert evt.message.model == "test-model"
        assert evt.message.stop_reason is None
        assert isinstance(evt.message.usage.input_tokens, int)
        assert isinstance(evt.message.usage.output_tokens, int)

    @pytest.mark.asyncio
    async def test_content_block_start_text(self):
        """content_block_start with type=text has all required fields."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "test"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        cbs = [d for t, d in events if t == "content_block_start"]
        assert len(cbs) >= 1

        evt = _validate_event("content_block_start", cbs[0])
        assert evt.content_block.type == "text"
        assert isinstance(evt.index, int)

    @pytest.mark.asyncio
    async def test_text_delta_event_fields(self):
        """content_block_delta with text_delta has all required fields."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "hello"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        deltas = [d for t, d in events if t == "content_block_delta"]
        text_deltas = [d for d in deltas if d.get("delta", {}).get("type") == "text_delta"]
        assert len(text_deltas) >= 1

        evt = _validate_event("content_block_delta", text_deltas[0])
        assert evt.delta.type == "text_delta"
        assert evt.delta.text == "hello"
        assert isinstance(evt.index, int)

    @pytest.mark.asyncio
    async def test_content_block_stop_fields(self):
        """content_block_stop has all required fields."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "x"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        stops = [d for t, d in events if t == "content_block_stop"]
        assert len(stops) >= 1

        evt = _validate_event("content_block_stop", stops[0])
        assert evt.type == "content_block_stop"
        assert isinstance(evt.index, int)

    @pytest.mark.asyncio
    async def test_message_delta_fields(self):
        """message_delta has stop_reason and usage."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "x"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        md = [d for t, d in events if t == "message_delta"]
        assert len(md) == 1

        evt = _validate_event("message_delta", md[0])
        assert evt.delta.stop_reason == "end_turn"
        assert isinstance(evt.usage.output_tokens, int)

    @pytest.mark.asyncio
    async def test_message_stop_fields(self):
        """message_stop has the correct type field."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "x"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        ms = [d for t, d in events if t == "message_stop"]
        assert len(ms) == 1

        evt = _validate_event("message_stop", ms[0])
        assert evt.type == "message_stop"

    @pytest.mark.asyncio
    async def test_ping_event_skipped_by_validator(self):
        """Ping events are present in the stream but not SDK-validated (no model)."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "hi"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        ping_events = [d for t, d in events if t == "ping"]
        assert len(ping_events) >= 1

    @pytest.mark.asyncio
    async def test_event_sequence_order(self):
        """Events follow the correct Anthropic ordering:
        message_start -> ping -> content_block_start -> deltas -> stop -> message_delta -> message_stop
        """
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "A"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "B"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        types = [t for t, _ in events]

        # message_start must be first
        assert types[0] == "message_start"
        # ping follows message_start
        assert types[1] == "ping"
        # message_delta must be second-to-last
        assert types[-2] == "message_delta"
        # message_stop must be last
        assert types[-1] == "message_stop"


# ---------------------------------------------------------------------------
# Tool call response path
# ---------------------------------------------------------------------------

class TestToolCallStreamValidation:
    """Validate all events in a tool-call streaming response."""

    @pytest.mark.asyncio
    async def test_tool_call_events_validate(self):
        """Tool call stream produces valid content_block events with tool_use."""
        chunks = [
            sse_chunk({"choices": [{"delta": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"index": 0, "id": "call_abc", "type": "function",
                                "function": {"name": "get_weather", "arguments": ""}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [{"index": 0, "function": {"arguments": '{"city":'}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [{"index": 0, "function": {"arguments": '"NYC"}'}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)

        types = [et for et, _ in validated]
        assert "content_block_start" in types
        assert "content_block_delta" in types
        assert "content_block_stop" in types
        assert "message_delta" in types

    @pytest.mark.asyncio
    async def test_tool_use_content_block_start(self):
        """content_block_start with type=tool_use has id, name, and input."""
        chunks = [
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [{"index": 0, "id": "call_xyz", "type": "function",
                                "function": {"name": "search", "arguments": "{}"}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        cbs = [d for t, d in events if t == "content_block_start"]
        tool_starts = [d for d in cbs if d.get("content_block", {}).get("type") == "tool_use"]
        assert len(tool_starts) >= 1

        evt = _validate_event("content_block_start", tool_starts[0])
        assert evt.content_block.type == "tool_use"
        assert evt.content_block.name == "search"
        assert isinstance(evt.content_block.id, str)
        assert evt.content_block.id.startswith("toolu_")

    @pytest.mark.asyncio
    async def test_input_json_delta(self):
        """content_block_delta with input_json_delta has partial_json."""
        chunks = [
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [{"index": 0, "id": "call_abc", "type": "function",
                                "function": {"name": "fn", "arguments": '{"key":'}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [{"index": 0, "function": {"arguments": '"val"}'}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        deltas = [d for t, d in events if t == "content_block_delta"]
        json_deltas = [d for d in deltas
                       if d.get("delta", {}).get("type") == "input_json_delta"]
        assert len(json_deltas) >= 1

        for jd in json_deltas:
            evt = _validate_event("content_block_delta", jd)
            assert evt.delta.type == "input_json_delta"
            assert isinstance(evt.delta.partial_json, str)

    @pytest.mark.asyncio
    async def test_tool_use_stop_reason(self):
        """Tool call streams produce message_delta with stop_reason=tool_use."""
        chunks = [
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [{"index": 0, "id": "call_abc", "type": "function",
                                "function": {"name": "fn", "arguments": "{}"}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        md = [d for t, d in events if t == "message_delta"]
        assert len(md) == 1

        evt = _validate_event("message_delta", md[0])
        assert evt.delta.stop_reason == "tool_use"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_all_validate(self):
        """Multiple tool calls each produce valid event sequences."""
        chunks = [
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [
                    {"index": 0, "id": "call_1", "type": "function",
                     "function": {"name": "fn_a", "arguments": '{"a":1}'}},
                    {"index": 1, "id": "call_2", "type": "function",
                     "function": {"name": "fn_b", "arguments": '{"b":2}'}},
                ]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)

        tool_starts = [(t, m) for t, m in validated
                       if t == "content_block_start" and m.content_block.type == "tool_use"]
        assert len(tool_starts) == 2
        names = {m.content_block.name for _, m in tool_starts}
        assert names == {"fn_a", "fn_b"}

    @pytest.mark.asyncio
    async def test_text_then_tool_call_validates(self):
        """A stream with text followed by a tool call validates fully."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "Let me search"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {
                "content": None,
                "tool_calls": [{"index": 0, "id": "call_x", "type": "function",
                                "function": {"name": "search", "arguments": '{"q":"test"}'}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]
        # Should have both text and tool_use content blocks
        starts = [(t, m) for t, m in validated if t == "content_block_start"]
        start_types = [m.content_block.type for _, m in starts]
        assert "text" in start_types
        assert "tool_use" in start_types


# ---------------------------------------------------------------------------
# Thinking response path
# ---------------------------------------------------------------------------

class TestThinkingStreamValidation:
    """Validate all events in a thinking/reasoning streaming response."""

    @pytest.mark.asyncio
    async def test_thinking_events_validate(self):
        """Thinking stream produces valid thinking content blocks."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "Let me think..."}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"reasoning_content": " about this."}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "The answer is 42."}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)

        types = [et for et, _ in validated]
        assert "content_block_start" in types
        assert "content_block_delta" in types

        # Should have thinking and text content blocks
        starts = [(t, m) for t, m in validated if t == "content_block_start"]
        start_types = [m.content_block.type for _, m in starts]
        assert "thinking" in start_types
        assert "text" in start_types

    @pytest.mark.asyncio
    async def test_thinking_delta_fields(self):
        """content_block_delta with thinking_delta has all required fields."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "pondering"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "answer"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        deltas = [d for t, d in events if t == "content_block_delta"]
        thinking_deltas = [d for d in deltas
                           if d.get("delta", {}).get("type") == "thinking_delta"]
        assert len(thinking_deltas) >= 1

        evt = _validate_event("content_block_delta", thinking_deltas[0])
        assert evt.delta.type == "thinking_delta"
        assert evt.delta.thinking == "pondering"
        assert isinstance(evt.index, int)

    @pytest.mark.asyncio
    async def test_signature_delta_fields(self):
        """content_block_delta with signature_delta has all required fields."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "think"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "answer"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        deltas = [d for t, d in events if t == "content_block_delta"]
        sig_deltas = [d for d in deltas
                      if d.get("delta", {}).get("type") == "signature_delta"]
        assert len(sig_deltas) >= 1

        evt = _validate_event("content_block_delta", sig_deltas[0])
        assert evt.delta.type == "signature_delta"
        assert isinstance(evt.delta.signature, str)

    @pytest.mark.asyncio
    async def test_thinking_block_start_has_signature(self):
        """content_block_start for thinking has signature field."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "think"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "done"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        starts = [d for t, d in events if t == "content_block_start"]
        thinking_starts = [d for d in starts
                          if d.get("content_block", {}).get("type") == "thinking"]
        assert len(thinking_starts) == 1

        evt = _validate_event("content_block_start", thinking_starts[0])
        assert evt.content_block.type == "thinking"
        assert hasattr(evt.content_block, "signature")

    @pytest.mark.asyncio
    async def test_thinking_only_stream_validates(self):
        """A stream with reasoning but no text still validates fully."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "just thinking"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]

        # Should have thinking content block
        starts = [(t, m) for t, m in validated if t == "content_block_start"]
        assert any(m.content_block.type == "thinking" for _, m in starts)

        # Must have message envelope
        assert "message_start" in types
        assert "message_delta" in types
        assert "message_stop" in types

    @pytest.mark.asyncio
    async def test_thinking_to_text_transition(self):
        """When transitioning from thinking to text, thinking block is properly
        closed with signature_delta before text block opens."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "step 1"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "The answer"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]

        # Find the index positions
        starts = [(i, t, m) for i, (t, m) in enumerate(validated) if t == "content_block_start"]
        assert len(starts) >= 2

        thinking_start_idx = None
        text_start_idx = None
        for idx, t, m in starts:
            if m.content_block.type == "thinking":
                thinking_start_idx = idx
            elif m.content_block.type == "text":
                text_start_idx = idx

        assert thinking_start_idx is not None
        assert text_start_idx is not None
        # Thinking must start before text
        assert thinking_start_idx < text_start_idx

        # Between thinking start and text start, there should be:
        # thinking_delta(s), signature_delta, content_block_stop
        between = validated[thinking_start_idx + 1:text_start_idx]
        between_types = [(t, getattr(m, 'delta', None)) for t, m in between]
        # Last event before text start should be content_block_stop
        assert between[-1][0] == "content_block_stop"


# ---------------------------------------------------------------------------
# Mixed response path
# ---------------------------------------------------------------------------

class TestMixedStreamValidation:
    """Validate streams with multiple content types (thinking + text + tool)."""

    @pytest.mark.asyncio
    async def test_thinking_text_tool_validates(self):
        """A stream with thinking, text, and tool call validates fully."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "Thinking..."}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "I'll search."}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [{"index": 0, "id": "call_x", "type": "function",
                                "function": {"name": "search", "arguments": '{"q":"test"}'}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]

        starts = [(t, m) for t, m in validated if t == "content_block_start"]
        start_types = [m.content_block.type for _, m in starts]
        assert "thinking" in start_types
        assert "text" in start_types
        assert "tool_use" in start_types

        # Should have exactly 3 content_block_stop events
        stops = [t for t, _ in validated if t == "content_block_stop"]
        assert len(stops) == 3

    @pytest.mark.asyncio
    async def test_content_block_indices_sequential(self):
        """Content block indices are sequential starting from 0."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "think"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "text"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [{"index": 0, "id": "call_z", "type": "function",
                                "function": {"name": "fn", "arguments": "{}"}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)

        starts = [(t, m) for t, m in validated if t == "content_block_start"]
        indices = [m.index for _, m in starts]
        assert indices == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_all_delta_types_present(self):
        """Thinking + text + tool produces thinking_delta, signature_delta,
        text_delta, and input_json_delta."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "hmm"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "ok"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [{"index": 0, "id": "call_a", "type": "function",
                                "function": {"name": "fn", "arguments": '{"x":1}'}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)

        delta_events = [(t, m) for t, m in validated if t == "content_block_delta"]
        delta_types = {m.delta.type for _, m in delta_events}
        assert "thinking_delta" in delta_types
        assert "signature_delta" in delta_types
        assert "text_delta" in delta_types
        assert "input_json_delta" in delta_types


# ---------------------------------------------------------------------------
# Empty response path
# ---------------------------------------------------------------------------

class TestEmptyStreamValidation:
    """Validate edge-case streams that produce minimal events."""

    @pytest.mark.asyncio
    async def test_empty_stream_validates(self):
        """A stream with only a finish chunk and DONE validates."""
        chunks = [
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]
        assert "message_start" in types
        assert "message_delta" in types
        assert "message_stop" in types

    @pytest.mark.asyncio
    async def test_done_only_stream_validates(self):
        """A stream with only data: [DONE] validates."""
        chunks = ["data: [DONE]\n\n"]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]
        assert "message_start" in types
        assert "message_delta" in types
        assert "message_stop" in types

    @pytest.mark.asyncio
    async def test_empty_stream_has_correct_stop_reason(self):
        """Empty stream message_delta defaults to end_turn stop_reason."""
        chunks = [
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        md = [d for t, d in events if t == "message_delta"]
        evt = _validate_event("message_delta", md[0])
        assert evt.delta.stop_reason == "end_turn"


# ---------------------------------------------------------------------------
# message_delta stop_reason variants
# ---------------------------------------------------------------------------

class TestStopReasonValidation:
    """Validate that all stop_reason values pass SDK validation."""

    @pytest.mark.asyncio
    async def test_end_turn(self):
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "done"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        md = [d for t, d in events if t == "message_delta"]
        evt = _validate_event("message_delta", md[0])
        assert evt.delta.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_max_tokens(self):
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "truncated"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "length"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 128, "total_tokens": 129}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        md = [d for t, d in events if t == "message_delta"]
        evt = _validate_event("message_delta", md[0])
        assert evt.delta.stop_reason == "max_tokens"

    @pytest.mark.asyncio
    async def test_tool_use(self):
        chunks = [
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [{"index": 0, "id": "call_x", "type": "function",
                                "function": {"name": "fn", "arguments": "{}"}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        md = [d for t, d in events if t == "message_delta"]
        evt = _validate_event("message_delta", md[0])
        assert evt.delta.stop_reason == "tool_use"

    @pytest.mark.asyncio
    async def test_stop_sequence(self):
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "hello\n\n"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks, stop_sequences=["\n\n"])
        md = [d for t, d in events if t == "message_delta"]
        evt = _validate_event("message_delta", md[0])
        assert evt.delta.stop_reason == "stop_sequence"
        assert evt.delta.stop_sequence == "\n\n"


# ---------------------------------------------------------------------------
# message_delta usage validation
# ---------------------------------------------------------------------------

class TestMessageDeltaUsageValidation:
    """Validate that message_delta usage fields pass SDK validation."""

    @pytest.mark.asyncio
    async def test_usage_has_output_tokens(self):
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "x"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        md = [d for t, d in events if t == "message_delta"]
        evt = _validate_event("message_delta", md[0])
        assert evt.usage.output_tokens == 5

    @pytest.mark.asyncio
    async def test_usage_has_cache_tokens(self):
        """Usage includes cache_creation_input_tokens and cache_read_input_tokens."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "x"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        md_data = [d for t, d in events if t == "message_delta"][0]
        # Validate raw dict has the fields
        usage = md_data.get("usage", {})
        assert "cache_creation_input_tokens" in usage
        assert "cache_read_input_tokens" in usage
        # Also validates via Pydantic
        _validate_event("message_delta", md_data)


# ---------------------------------------------------------------------------
# Non-streaming Message model validation
# ---------------------------------------------------------------------------

class TestNonStreamingMessageValidation:
    """Validate that non-streaming Anthropic responses pass Message model validation."""

    def test_text_response_validates(self):
        """A plain text non-streaming response validates as a Message."""
        result = openai_result(content="Hello world", prompt_tokens=10, completion_tokens=5)
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)
        assert validated.role == "assistant"
        assert validated.model == "test-model"
        assert validated.stop_reason == "end_turn"
        assert len(validated.content) >= 1
        assert validated.content[0].type == "text"
        assert validated.content[0].text == "Hello world"

    def test_tool_use_response_validates(self):
        """A tool call non-streaming response validates."""
        result = openai_result(content=None, finish_reason="tool_calls")
        result["choices"][0]["message"]["tool_calls"] = [{
            "id": "call_abc",
            "type": "function",
            "function": {"name": "search", "arguments": '{"q":"test"}'},
        }]
        result["choices"][0]["message"]["content"] = None

        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)
        assert validated.stop_reason == "tool_use"
        tool_blocks = [c for c in validated.content if c.type == "tool_use"]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].name == "search"
        assert isinstance(tool_blocks[0].id, str)
        assert tool_blocks[0].id.startswith("toolu_")

    def test_thinking_response_validates(self):
        """A thinking non-streaming response validates."""
        result = openai_result(content="The answer", reasoning_content="Let me think")
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)
        thinking_blocks = [c for c in validated.content if c.type == "thinking"]
        text_blocks = [c for c in validated.content if c.type == "text"]
        assert len(thinking_blocks) == 1
        assert thinking_blocks[0].thinking == "Let me think"
        assert len(text_blocks) == 1
        assert text_blocks[0].text == "The answer"

    def test_empty_response_validates(self):
        """A response with no content still validates (empty text block)."""
        result = openai_result(content=None, finish_reason="stop")
        result["choices"][0]["message"]["content"] = None
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)
        assert validated.stop_reason == "end_turn"
        assert len(validated.content) >= 1

    def test_usage_fields_validate(self):
        """Non-streaming usage includes all required fields."""
        result = openai_result(prompt_tokens=20, completion_tokens=10)
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)
        assert validated.usage.input_tokens == 20
        assert validated.usage.output_tokens == 10
        assert validated.usage.cache_creation_input_tokens == 0
        assert validated.usage.cache_read_input_tokens == 0

    def test_max_tokens_stop_reason_validates(self):
        """finish_reason=length maps to stop_reason=max_tokens."""
        result = openai_result(content="truncated", finish_reason="length")
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)
        assert validated.stop_reason == "max_tokens"
        assert validated.stop_sequence is None

    def test_stop_sequence_validates(self):
        """stop_reason=stop_sequence with a stop_sequence value validates."""
        result = openai_result(content="hello\n\n", finish_reason="stop")
        resp = anthropic_compat._build_anthropic_response(
            result, "test-model", stop_sequences=["\n\n"]
        )
        validated = sdk.Message.model_validate(resp)
        assert validated.stop_reason == "stop_sequence"
        assert validated.stop_sequence == "\n\n"

    def test_mixed_content_validates(self):
        """A response with thinking + text + tool_use validates."""
        result = openai_result(content="Let me search", reasoning_content="hmm",
                               finish_reason="tool_calls")
        result["choices"][0]["message"]["tool_calls"] = [{
            "id": "call_abc",
            "type": "function",
            "function": {"name": "search", "arguments": '{"q":"x"}'},
        }]
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)
        types = [c.type for c in validated.content]
        assert "thinking" in types
        assert "text" in types
        assert "tool_use" in types

    def test_message_id_format(self):
        """Message ID starts with msg_ prefix."""
        result = openai_result()
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)
        assert validated.id.startswith("msg_")

    def test_message_type_field(self):
        """Message type is 'message'."""
        result = openai_result()
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)
        assert validated.type == "message"

    def test_model_echoed_in_response(self):
        """The request model name is echoed in the response."""
        result = openai_result()
        resp = anthropic_compat._build_anthropic_response(result, "claude-3-opus")
        validated = sdk.Message.model_validate(resp)
        assert validated.model == "claude-3-opus"


# ---------------------------------------------------------------------------
# message_start message object validation
# ---------------------------------------------------------------------------

class TestMessageStartMessageValidation:
    """Validate the Message object embedded in message_start events."""

    @pytest.mark.asyncio
    async def test_message_start_message_validates_as_message(self):
        """The message_start.message can be validated as a full Message model."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "hi"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        msg_start = [d for t, d in events if t == "message_start"]
        assert len(msg_start) == 1

        # The embedded message should validate as a Message
        msg_data = msg_start[0]["message"]
        validated = sdk.Message.model_validate(msg_data)
        assert validated.id.startswith("msg_")
        assert validated.role == "assistant"
        assert validated.content == []
        assert validated.stop_reason is None
        assert validated.usage.input_tokens == 0
        assert validated.usage.output_tokens == 0


# ---------------------------------------------------------------------------
# Error mid-stream validation
# ---------------------------------------------------------------------------

class TestMidStreamErrorValidation:
    """Validate that mid-stream errors produce valid event sequences."""

    @pytest.mark.asyncio
    async def test_exception_produces_valid_events(self):
        """A mid-stream exception still produces a validatable event sequence."""
        async def _error_stream():
            yield sse_chunk({"choices": [{"delta": {"content": "start"}, "index": 0}]})
            raise RuntimeError("Backend exploded")

        raw_output = []
        async for sse_str in anthropic_compat._anthropic_stream_converter(
            _error_stream(), "test-model"
        ):
            raw_output.append(sse_str)

        full_text = "".join(raw_output)
        events = _parse_sse_events(full_text)
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]

        # Must have complete envelope
        assert "message_start" in types
        assert "message_delta" in types
        assert "message_stop" in types

    @pytest.mark.asyncio
    async def test_backend_error_produces_valid_events(self):
        """A BackendError mid-stream still produces a validatable event sequence."""
        from llm import BackendError

        async def _backend_error_stream():
            yield sse_chunk({"choices": [{"delta": {"content": "partial"}, "index": 0}]})
            raise BackendError(429, "rate limited")

        raw_output = []
        async for sse_str in anthropic_compat._anthropic_stream_converter(
            _backend_error_stream(), "test-model"
        ):
            raw_output.append(sse_str)

        full_text = "".join(raw_output)
        events = _parse_sse_events(full_text)
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]

        assert "message_start" in types
        assert "message_delta" in types
        assert "message_stop" in types

    @pytest.mark.asyncio
    async def test_backend_error_emits_structured_error_event(self):
        """BackendError streams include Anthropic's structured error SSE frame."""
        from llm import BackendError

        async def _backend_error_stream():
            yield sse_chunk({"choices": [{"delta": {"content": "partial"}, "index": 0}]})
            raise BackendError(429, "raw upstream rate limit")

        raw_output = []
        async for sse_str in anthropic_compat._anthropic_stream_converter(
            _backend_error_stream(), "test-model"
        ):
            raw_output.append(sse_str)

        full_text = "".join(raw_output)
        events = _parse_sse_events(full_text)
        validated = _validate_all_events(events)
        error_events = [m for t, m in validated if t == "error"]
        types = [t for t, _ in validated]

        assert error_events
        assert error_events[0].type == "error"
        assert error_events[0].error.type == "rate_limit_error"
        assert error_events[0].error.message == "Rate limit exceeded"
        assert "raw upstream rate limit" not in full_text
        assert "message_delta" in types
        assert "message_stop" in types

    @pytest.mark.asyncio
    async def test_error_during_thinking_produces_valid_events(self):
        """Error while thinking block is open produces valid event sequence."""
        async def _error_stream():
            yield sse_chunk({"choices": [{"delta": {"reasoning_content": "thinking"}, "index": 0}]})
            raise RuntimeError("Boom")

        raw_output = []
        async for sse_str in anthropic_compat._anthropic_stream_converter(
            _error_stream(), "test-model"
        ):
            raw_output.append(sse_str)

        full_text = "".join(raw_output)
        events = _parse_sse_events(full_text)
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]

        assert "message_start" in types
        assert "message_delta" in types
        assert "message_stop" in types

        # All content blocks that were opened should be closed
        open_indices = set()
        for t, m in validated:
            if t == "content_block_start":
                open_indices.add(m.index)
            elif t == "content_block_stop":
                open_indices.discard(m.index)
        assert len(open_indices) == 0, f"Unclosed blocks: {open_indices}"


# ---------------------------------------------------------------------------
# Comprehensive non-streaming response variations
# ---------------------------------------------------------------------------

class TestNonStreamingMultipleContentBlocks:
    """Validate non-streaming responses with multiple content block combinations."""

    def test_text_plus_tool_use_plus_thinking_validates(self):
        """Response with thinking + text + tool_use content blocks validates."""
        result = openai_result(content="I'll search for that.",
                               reasoning_content="Let me reason about this query.",
                               finish_reason="tool_calls")
        result["choices"][0]["message"]["tool_calls"] = [{
            "id": "call_abc123",
            "type": "function",
            "function": {"name": "web_search", "arguments": '{"query":"test"}'},
        }]
        resp = anthropic_compat._build_anthropic_response(result, "claude-3-opus")
        validated = sdk.Message.model_validate(resp)

        types = [c.type for c in validated.content]
        assert "thinking" in types
        assert "text" in types
        assert "tool_use" in types
        assert len(validated.content) == 3
        # Order: thinking first, then text, then tool_use
        assert types == ["thinking", "text", "tool_use"]

    def test_only_tool_use_blocks_validates(self):
        """Response with only tool_use blocks (no text content) validates."""
        result = openai_result(content=None, finish_reason="tool_calls")
        result["choices"][0]["message"]["content"] = None
        result["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city":"NYC"}'},
            },
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "get_time", "arguments": '{"tz":"UTC"}'},
            },
        ]
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)

        assert validated.stop_reason == "tool_use"
        assert all(c.type == "tool_use" for c in validated.content)
        assert len(validated.content) == 2
        names = {c.name for c in validated.content}
        assert names == {"get_weather", "get_time"}
        # Each tool_use block should have parsed input
        for block in validated.content:
            assert isinstance(block.input, dict)
            assert isinstance(block.id, str)
            assert block.id.startswith("toolu_")

    def test_thinking_plus_signature_validates(self):
        """Response with thinking block (which includes signature) validates."""
        result = openai_result(content="The answer is 42.",
                               reasoning_content="Deep thinking about the question.")
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)

        thinking_blocks = [c for c in validated.content if c.type == "thinking"]
        assert len(thinking_blocks) == 1
        assert thinking_blocks[0].thinking == "Deep thinking about the question."
        assert thinking_blocks[0].signature == ""
        # Text block follows
        text_blocks = [c for c in validated.content if c.type == "text"]
        assert len(text_blocks) == 1
        assert text_blocks[0].text == "The answer is 42."

    def test_stop_reason_stop_sequence_validates(self):
        """Response with stop_reason=stop_sequence validates with stop_sequence value."""
        result = openai_result(content="Hello world\n\nHuman:", finish_reason="stop")
        resp = anthropic_compat._build_anthropic_response(
            result, "test-model", stop_sequences=["\n\nHuman:"]
        )
        validated = sdk.Message.model_validate(resp)

        assert validated.stop_reason == "stop_sequence"
        assert validated.stop_sequence == "\n\nHuman:"

    def test_max_usage_values_validates(self):
        """Response with large token usage values validates."""
        result = openai_result(content="response text",
                               prompt_tokens=128000, completion_tokens=4096)
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)

        assert validated.usage.input_tokens == 128000
        assert validated.usage.output_tokens == 4096

    def test_cache_usage_fields_validate(self):
        """Response with cache usage fields set to zero validates."""
        result = openai_result(content="cached response")
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)

        assert validated.usage.cache_creation_input_tokens == 0
        assert validated.usage.cache_read_input_tokens == 0
        assert isinstance(validated.usage.input_tokens, int)
        assert isinstance(validated.usage.output_tokens, int)


class TestNonStreamingCountTokensValidation:
    """Validate count_tokens response against Anthropic SDK model."""

    def test_count_tokens_response_validates(self):
        """A count_tokens response validates as MessageTokensCount."""
        resp_data = {"input_tokens": 42}
        validated = sdk.MessageTokensCount.model_validate(resp_data)
        assert validated.input_tokens == 42

    def test_count_tokens_zero_validates(self):
        """Zero token count validates."""
        resp_data = {"input_tokens": 0}
        validated = sdk.MessageTokensCount.model_validate(resp_data)
        assert validated.input_tokens == 0

    def test_count_tokens_large_value_validates(self):
        """Large token count validates."""
        resp_data = {"input_tokens": 200000}
        validated = sdk.MessageTokensCount.model_validate(resp_data)
        assert validated.input_tokens == 200000


class TestNonStreamingEdgeCases:
    """Validate edge-case non-streaming responses."""

    def test_multiple_tool_calls_validates(self):
        """Response with multiple tool calls validates with correct IDs."""
        result = openai_result(content=None, finish_reason="tool_calls")
        result["choices"][0]["message"]["content"] = None
        result["choices"][0]["message"]["tool_calls"] = [
            {"id": "call_a", "type": "function",
             "function": {"name": "fn1", "arguments": '{"x":1}'}},
            {"id": "call_b", "type": "function",
             "function": {"name": "fn2", "arguments": '{"y":2}'}},
            {"id": "call_c", "type": "function",
             "function": {"name": "fn3", "arguments": '{"z":3}'}},
        ]
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)

        assert len(validated.content) == 3
        for block in validated.content:
            assert block.type == "tool_use"
            assert block.id.startswith("toolu_")
            assert isinstance(block.input, dict)
            assert isinstance(block.name, str)

    def test_text_with_tool_calls_validates(self):
        """Response with both text content and tool calls validates."""
        result = openai_result(content="Let me help with that.", finish_reason="tool_calls")
        result["choices"][0]["message"]["tool_calls"] = [{
            "id": "call_xyz",
            "type": "function",
            "function": {"name": "calculator", "arguments": '{"expr":"2+2"}'},
        }]
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)

        types = [c.type for c in validated.content]
        assert "text" in types
        assert "tool_use" in types
        assert validated.stop_reason == "tool_use"

    def test_thinking_only_validates(self):
        """Response with only thinking content (no text) validates."""
        result = openai_result(content=None, reasoning_content="Internal reasoning only.")
        result["choices"][0]["message"]["content"] = None
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)

        # Should have thinking block only (no empty text fallback when thinking exists)
        types = [c.type for c in validated.content]
        assert "thinking" in types
        assert len(validated.content) == 1
        assert validated.content[0].thinking == "Internal reasoning only."

    def test_zero_usage_validates(self):
        """Response with zero token usage validates."""
        result = openai_result(content="", prompt_tokens=0, completion_tokens=0)
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)

        assert validated.usage.input_tokens == 0
        assert validated.usage.output_tokens == 0

    def test_all_fields_present_validates(self):
        """All expected Message fields are present and correctly typed."""
        result = openai_result(content="Complete response.")
        resp = anthropic_compat._build_anthropic_response(result, "claude-3.5-sonnet")
        validated = sdk.Message.model_validate(resp)

        assert isinstance(validated.id, str)
        assert validated.id.startswith("msg_")
        assert validated.type == "message"
        assert validated.role == "assistant"
        assert isinstance(validated.model, str)
        assert validated.model == "claude-3.5-sonnet"
        assert isinstance(validated.content, list)
        assert validated.stop_reason in ("end_turn", "max_tokens", "stop_sequence", "tool_use")
        assert isinstance(validated.usage, sdk.Usage)

    def test_tool_use_with_empty_arguments_validates(self):
        """Tool use with empty object arguments validates."""
        result = openai_result(content=None, finish_reason="tool_calls")
        result["choices"][0]["message"]["content"] = None
        result["choices"][0]["message"]["tool_calls"] = [{
            "id": "call_empty",
            "type": "function",
            "function": {"name": "no_args_tool", "arguments": "{}"},
        }]
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)

        tool_blocks = [c for c in validated.content if c.type == "tool_use"]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].input == {}

    def test_tool_use_with_complex_arguments_validates(self):
        """Tool use with nested/complex arguments validates."""
        complex_args = '{"filters":{"status":"active","tags":["a","b"]},"limit":10,"nested":{"deep":{"value":true}}}'
        result = openai_result(content=None, finish_reason="tool_calls")
        result["choices"][0]["message"]["content"] = None
        result["choices"][0]["message"]["tool_calls"] = [{
            "id": "call_complex",
            "type": "function",
            "function": {"name": "complex_tool", "arguments": complex_args},
        }]
        resp = anthropic_compat._build_anthropic_response(result, "test-model")
        validated = sdk.Message.model_validate(resp)

        tool_blocks = [c for c in validated.content if c.type == "tool_use"]
        assert len(tool_blocks) == 1
        assert isinstance(tool_blocks[0].input, dict)
        assert tool_blocks[0].input["limit"] == 10
        assert tool_blocks[0].input["filters"]["status"] == "active"
