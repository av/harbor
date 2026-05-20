"""Comprehensive Pydantic model validation for all Responses API SSE events.

Every SSE event our Responses API produces is constructed by hand as a dict
and fed to the corresponding OpenAI SDK Pydantic model's ``model_validate``
method.  If any required field is missing, the wrong type, or mis-named, the
test fails — catching SDK incompatibilities at unit-test time rather than
at runtime with a real client.

Covered event paths:
  - Text-only response (created, in_progress, output_item.added, content_part.added,
    output_text.delta, output_text.done, content_part.done, output_item.done, completed)
  - Tool call response (function_call_arguments.delta, function_call_arguments.done)
  - Reasoning response (reasoning_summary_text.delta, reasoning_summary_text.done,
    reasoning_summary_part.added, reasoning_summary_part.done)
  - Refusal response (refusal.delta, refusal.done)
  - Error / failed response (response.failed)
  - Incomplete response (response.incomplete)
  - Annotation events (output_text.annotation.added)
"""

import json
import sys
import os
import asyncio
from unittest.mock import MagicMock, patch

import pytest

import openai.types.responses as sdk

# Ensure src dir is on the path (conftest.py handles this, but be explicit)
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import responses_compat
from helpers import FakeLLM, sse_chunk, openai_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_sse_events(raw_chunks):
    """Parse SSE event strings into (event_type, data_dict) pairs."""
    events = []
    for raw in raw_chunks:
        lines = raw.strip().split("\n")
        event_type = None
        data_str = None
        for line in lines:
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
        if event_type and data_str:
            events.append((event_type, json.loads(data_str)))
    return events


def _validate_event(event_type, data):
    """Validate a single SSE event dict against the corresponding Pydantic model.

    Returns the validated model instance, or raises on failure.
    """
    MODEL_MAP = {
        "response.created": sdk.ResponseCreatedEvent,
        "response.in_progress": sdk.ResponseInProgressEvent,
        "response.completed": sdk.ResponseCompletedEvent,
        "response.incomplete": sdk.ResponseIncompleteEvent,
        "response.failed": sdk.ResponseFailedEvent,
        "response.output_item.added": sdk.ResponseOutputItemAddedEvent,
        "response.output_item.done": sdk.ResponseOutputItemDoneEvent,
        "response.content_part.added": sdk.ResponseContentPartAddedEvent,
        "response.content_part.done": sdk.ResponseContentPartDoneEvent,
        "response.output_text.delta": sdk.ResponseTextDeltaEvent,
        "response.output_text.done": sdk.ResponseTextDoneEvent,
        "response.function_call_arguments.delta": sdk.ResponseFunctionCallArgumentsDeltaEvent,
        "response.function_call_arguments.done": sdk.ResponseFunctionCallArgumentsDoneEvent,
        "response.reasoning_summary_part.added": sdk.ResponseReasoningSummaryPartAddedEvent,
        "response.reasoning_summary_part.done": sdk.ResponseReasoningSummaryPartDoneEvent,
        "response.reasoning_summary_text.delta": sdk.ResponseReasoningSummaryTextDeltaEvent,
        "response.reasoning_summary_text.done": sdk.ResponseReasoningSummaryTextDoneEvent,
        "response.refusal.delta": sdk.ResponseRefusalDeltaEvent,
        "response.refusal.done": sdk.ResponseRefusalDoneEvent,
        "response.output_text.annotation.added": sdk.ResponseOutputTextAnnotationAddedEvent,
    }
    model_cls = MODEL_MAP.get(event_type)
    if model_cls is None:
        pytest.fail(f"Unknown event type: {event_type}")
    return model_cls.model_validate(data)


def _validate_all_events(events):
    """Validate every event in a list of (event_type, data) pairs.

    Returns a list of (event_type, validated_model) pairs.
    """
    validated = []
    for event_type, data in events:
        model = _validate_event(event_type, data)
        validated.append((event_type, model))
    return validated


async def _run_stream_converter(chunks, request_model="test-model",
                                 response_id="resp_test123", request_body=None):
    """Run the streaming converter with mock chunks and collect output events."""
    async def _fake_stream():
        for chunk in chunks:
            yield chunk

    events = []
    async for sse_str in responses_compat._responses_stream_converter(
        _fake_stream(), request_model, response_id, request_body=request_body
    ):
        events.append(sse_str)
    return _parse_sse_events(events)


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

        # Verify expected event sequence
        types = [et for et, _ in validated]
        assert types[0] == "response.created"
        assert types[1] == "response.in_progress"
        assert "response.output_item.added" in types
        assert "response.content_part.added" in types
        assert "response.output_text.delta" in types
        assert "response.output_text.done" in types
        assert "response.content_part.done" in types
        assert "response.output_item.done" in types
        assert types[-1] == "response.completed"

    @pytest.mark.asyncio
    async def test_created_event_has_valid_response(self):
        """The response.created event carries a valid Response object."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "Hi"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        created_evt = _validate_event("response.created", events[0][1])
        assert created_evt.type == "response.created"
        assert isinstance(created_evt.sequence_number, int)
        # The embedded response object should be a valid Response
        resp = created_evt.response
        assert resp.object == "response"
        assert resp.status == "in_progress"

    @pytest.mark.asyncio
    async def test_text_delta_event_fields(self):
        """output_text.delta events have all required fields."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "test"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        delta_events = [(t, d) for t, d in events if t == "response.output_text.delta"]
        assert len(delta_events) >= 1

        evt = _validate_event("response.output_text.delta", delta_events[0][1])
        assert evt.delta == "test"
        assert isinstance(evt.logprobs, list)
        assert isinstance(evt.content_index, int)
        assert isinstance(evt.output_index, int)
        assert isinstance(evt.item_id, str)

    @pytest.mark.asyncio
    async def test_text_done_event_has_full_text(self):
        """output_text.done carries the complete accumulated text."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "Hello"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": " world"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        done_events = [(t, d) for t, d in events if t == "response.output_text.done"]
        assert len(done_events) == 1

        evt = _validate_event("response.output_text.done", done_events[0][1])
        assert evt.text == "Hello world"
        assert isinstance(evt.logprobs, list)

    @pytest.mark.asyncio
    async def test_content_part_done_has_output_text(self):
        """content_part.done carries a valid output_text part."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "Hi"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        cp_done = [(t, d) for t, d in events if t == "response.content_part.done"]
        assert len(cp_done) >= 1

        evt = _validate_event("response.content_part.done", cp_done[0][1])
        assert evt.part.type == "output_text"
        assert evt.part.text == "Hi"

    @pytest.mark.asyncio
    async def test_output_item_done_message(self):
        """output_item.done for a message has valid structure."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "Done"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        oi_done = [(t, d) for t, d in events if t == "response.output_item.done"]
        # There should be at least one output_item.done for the message
        msg_items = [d for _, d in oi_done if d.get("item", {}).get("type") == "message"]
        assert len(msg_items) >= 1

        evt = _validate_event("response.output_item.done", msg_items[0])
        assert evt.item.type == "message"
        assert evt.item.role == "assistant"
        assert evt.item.status == "completed"

    @pytest.mark.asyncio
    async def test_completed_event_has_usage(self):
        """response.completed carries proper usage with token details."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "x"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        completed = [(t, d) for t, d in events if t == "response.completed"]
        assert len(completed) == 1

        evt = _validate_event("response.completed", completed[0][1])
        resp = evt.response
        assert resp.status == "completed"
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 5
        assert resp.usage.total_tokens == 15
        assert resp.usage.input_tokens_details.cached_tokens == 0
        assert resp.usage.output_tokens_details.reasoning_tokens == 0

    @pytest.mark.asyncio
    async def test_sequence_numbers_monotonic(self):
        """All events have monotonically increasing sequence_number."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "a"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "b"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)
        seq_numbers = [m.sequence_number for _, m in validated]
        for i in range(1, len(seq_numbers)):
            assert seq_numbers[i] > seq_numbers[i - 1], \
                f"sequence_number not monotonic: {seq_numbers[i-1]} -> {seq_numbers[i]}"


# ---------------------------------------------------------------------------
# Tool call response path
# ---------------------------------------------------------------------------

class TestToolCallStreamValidation:
    """Validate all events in a tool-call streaming response."""

    @pytest.mark.asyncio
    async def test_tool_call_events_validate(self):
        """Tool call stream produces valid function_call_arguments events."""
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
        assert "response.function_call_arguments.delta" in types
        assert "response.function_call_arguments.done" in types

    @pytest.mark.asyncio
    async def test_function_call_arguments_delta_fields(self):
        """function_call_arguments.delta has all required fields."""
        chunks = [
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [{"index": 0, "id": "call_abc", "type": "function",
                                "function": {"name": "test_fn", "arguments": '{"x":1}'}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        delta_events = [(t, d) for t, d in events
                        if t == "response.function_call_arguments.delta"]
        assert len(delta_events) >= 1

        evt = _validate_event("response.function_call_arguments.delta", delta_events[0][1])
        assert isinstance(evt.delta, str)
        assert isinstance(evt.item_id, str)
        assert isinstance(evt.output_index, int)
        assert isinstance(evt.sequence_number, int)

    @pytest.mark.asyncio
    async def test_function_call_arguments_done_fields(self):
        """function_call_arguments.done has arguments and name."""
        chunks = [
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [{"index": 0, "id": "call_abc", "type": "function",
                                "function": {"name": "lookup", "arguments": '{"q":"hi"}'}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        done_events = [(t, d) for t, d in events
                       if t == "response.function_call_arguments.done"]
        assert len(done_events) == 1

        evt = _validate_event("response.function_call_arguments.done", done_events[0][1])
        assert evt.arguments == '{"q":"hi"}'
        assert evt.name == "lookup"

    @pytest.mark.asyncio
    async def test_function_call_output_item_done(self):
        """output_item.done for a function_call has all required fields."""
        chunks = [
            sse_chunk({"choices": [{"delta": {
                "tool_calls": [{"index": 0, "id": "call_abc", "type": "function",
                                "function": {"name": "search", "arguments": "{}"}}]
            }, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        oi_done = [(t, d) for t, d in events if t == "response.output_item.done"]
        fc_items = [d for _, d in oi_done if d.get("item", {}).get("type") == "function_call"]
        assert len(fc_items) == 1

        evt = _validate_event("response.output_item.done", fc_items[0])
        assert evt.item.type == "function_call"
        assert evt.item.name == "search"
        assert isinstance(evt.item.arguments, str)
        assert isinstance(evt.item.call_id, str)

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

        done_events = [(t, m) for t, m in validated
                       if t == "response.function_call_arguments.done"]
        assert len(done_events) == 2
        names = {m.name for _, m in done_events}
        assert names == {"fn_a", "fn_b"}

    @pytest.mark.asyncio
    async def test_text_then_tool_call_validates(self):
        """A stream with text followed by tool calls validates fully."""
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
        # All events should validate without error
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]
        assert "response.output_text.delta" in types
        assert "response.function_call_arguments.done" in types


# ---------------------------------------------------------------------------
# Reasoning response path
# ---------------------------------------------------------------------------

class TestReasoningStreamValidation:
    """Validate all events in a reasoning/thinking streaming response."""

    @pytest.mark.asyncio
    async def test_reasoning_events_validate(self):
        """Reasoning stream produces valid summary events."""
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
        assert "response.reasoning_summary_text.delta" in types
        assert "response.reasoning_summary_text.done" in types
        assert "response.reasoning_summary_part.added" in types
        assert "response.reasoning_summary_part.done" in types
        # Also has text events after reasoning
        assert "response.output_text.delta" in types

    @pytest.mark.asyncio
    async def test_reasoning_summary_text_delta_fields(self):
        """reasoning_summary_text.delta has all required fields."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "thinking"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "answer"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        deltas = [(t, d) for t, d in events
                  if t == "response.reasoning_summary_text.delta"]
        assert len(deltas) >= 1

        evt = _validate_event("response.reasoning_summary_text.delta", deltas[0][1])
        assert evt.delta == "thinking"
        assert isinstance(evt.item_id, str)
        assert isinstance(evt.summary_index, int)
        assert isinstance(evt.output_index, int)

    @pytest.mark.asyncio
    async def test_reasoning_summary_text_done_fields(self):
        """reasoning_summary_text.done carries the full reasoning text."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "step 1"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"reasoning_content": " step 2"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "result"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        done = [(t, d) for t, d in events
                if t == "response.reasoning_summary_text.done"]
        assert len(done) == 1

        evt = _validate_event("response.reasoning_summary_text.done", done[0][1])
        assert evt.text == "step 1 step 2"

    @pytest.mark.asyncio
    async def test_reasoning_summary_part_added_fields(self):
        """reasoning_summary_part.added has valid part structure."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "think"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "result"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        added = [(t, d) for t, d in events
                 if t == "response.reasoning_summary_part.added"]
        assert len(added) == 1

        evt = _validate_event("response.reasoning_summary_part.added", added[0][1])
        assert evt.part.type == "summary_text"
        assert evt.part.text == ""
        assert isinstance(evt.summary_index, int)

    @pytest.mark.asyncio
    async def test_reasoning_summary_part_done_fields(self):
        """reasoning_summary_part.done has valid part with full text."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "deep thought"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "42"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        done = [(t, d) for t, d in events
                if t == "response.reasoning_summary_part.done"]
        assert len(done) == 1

        evt = _validate_event("response.reasoning_summary_part.done", done[0][1])
        assert evt.part.type == "summary_text"
        assert evt.part.text == "deep thought"

    @pytest.mark.asyncio
    async def test_reasoning_output_item_done(self):
        """output_item.done for reasoning has valid structure."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "think"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"content": "answer"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        oi_done = [(t, d) for t, d in events if t == "response.output_item.done"]
        reasoning_items = [d for _, d in oi_done
                           if d.get("item", {}).get("type") == "reasoning"]
        assert len(reasoning_items) == 1

        evt = _validate_event("response.output_item.done", reasoning_items[0])
        assert evt.item.type == "reasoning"
        assert len(evt.item.summary) >= 1
        assert evt.item.summary[0].type == "summary_text"

    @pytest.mark.asyncio
    async def test_reasoning_only_stream_validates(self):
        """A stream with reasoning but no text still validates fully."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "just thinking"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        # All events should validate
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]
        assert "response.reasoning_summary_text.delta" in types
        assert "response.completed" in types


# ---------------------------------------------------------------------------
# Refusal response path
# ---------------------------------------------------------------------------

class TestRefusalStreamValidation:
    """Validate all events in a refusal streaming response."""

    @pytest.mark.asyncio
    async def test_refusal_events_validate(self):
        """Refusal stream produces valid refusal events."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"refusal": "I cannot"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"refusal": " do that."}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)

        types = [et for et, _ in validated]
        assert "response.refusal.delta" in types
        assert "response.refusal.done" in types

    @pytest.mark.asyncio
    async def test_refusal_delta_fields(self):
        """refusal.delta has all required fields."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"refusal": "No"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        deltas = [(t, d) for t, d in events if t == "response.refusal.delta"]
        assert len(deltas) >= 1

        evt = _validate_event("response.refusal.delta", deltas[0][1])
        assert evt.delta == "No"
        assert isinstance(evt.content_index, int)
        assert isinstance(evt.item_id, str)
        assert isinstance(evt.output_index, int)

    @pytest.mark.asyncio
    async def test_refusal_done_fields(self):
        """refusal.done carries the full refusal text."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"refusal": "Cannot "}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {"refusal": "comply."}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        done = [(t, d) for t, d in events if t == "response.refusal.done"]
        assert len(done) == 1

        evt = _validate_event("response.refusal.done", done[0][1])
        assert evt.refusal == "Cannot comply."

    @pytest.mark.asyncio
    async def test_refusal_output_item_done(self):
        """output_item.done for refusal message has valid structure."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"refusal": "No"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        oi_done = [(t, d) for t, d in events if t == "response.output_item.done"]
        msg_items = [d for _, d in oi_done if d.get("item", {}).get("type") == "message"]
        assert len(msg_items) >= 1

        evt = _validate_event("response.output_item.done", msg_items[0])
        assert evt.item.type == "message"
        refusal_parts = [c for c in evt.item.content if c.type == "refusal"]
        assert len(refusal_parts) >= 1


# ---------------------------------------------------------------------------
# Error / failed response path
# ---------------------------------------------------------------------------

class TestFailedStreamValidation:
    """Validate the response.failed event on stream errors."""

    @pytest.mark.asyncio
    async def test_failed_event_validates_on_exception(self):
        """A mid-stream exception produces a valid response.failed event."""
        async def _error_stream():
            yield sse_chunk({"choices": [{"delta": {"content": "start"}, "index": 0}]})
            raise RuntimeError("Backend exploded")

        events = []
        async for sse_str in responses_compat._responses_stream_converter(
            _error_stream(), "test-model", "resp_err1"
        ):
            events.append(sse_str)

        parsed = _parse_sse_events(events)
        validated = _validate_all_events(parsed)
        types = [t for t, _ in validated]
        assert "response.failed" in types

        failed = [(t, m) for t, m in validated if t == "response.failed"]
        assert len(failed) == 1
        assert failed[0][1].response.status == "failed"

    @pytest.mark.asyncio
    async def test_failed_event_has_valid_response(self):
        """The response inside response.failed passes Response validation."""
        from llm import BackendError

        async def _backend_error_stream():
            raise BackendError(429, "rate limited")
            yield  # make it an async generator

        events = []
        async for sse_str in responses_compat._responses_stream_converter(
            _backend_error_stream(), "test-model", "resp_err2"
        ):
            events.append(sse_str)

        parsed = _parse_sse_events(events)
        validated = _validate_all_events(parsed)
        types = [t for t, _ in validated]
        assert "response.failed" in types


# ---------------------------------------------------------------------------
# Incomplete response path
# ---------------------------------------------------------------------------

class TestIncompleteStreamValidation:
    """Validate the response.incomplete event for length-limited responses."""

    @pytest.mark.asyncio
    async def test_incomplete_event_validates(self):
        """finish_reason='length' produces a valid response.incomplete event."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "truncated"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "length"}],
                       "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]
        assert "response.incomplete" in types

        incomplete = [(t, m) for t, m in validated if t == "response.incomplete"]
        assert len(incomplete) == 1
        assert incomplete[0][1].response.status == "incomplete"

    @pytest.mark.asyncio
    async def test_content_filter_produces_incomplete(self):
        """finish_reason='content_filter' also produces response.incomplete."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "filtered"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "content_filter"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]
        assert "response.incomplete" in types

    @pytest.mark.asyncio
    async def test_incomplete_has_details(self):
        """response.incomplete carries incomplete_details with reason."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "x"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "length"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        events = await _run_stream_converter(chunks)
        incomplete_events = [(t, d) for t, d in events if t == "response.incomplete"]
        assert len(incomplete_events) == 1

        evt = _validate_event("response.incomplete", incomplete_events[0][1])
        resp = evt.response
        assert resp.incomplete_details is not None
        assert resp.incomplete_details.reason == "max_output_tokens"


# ---------------------------------------------------------------------------
# Non-streaming Pydantic validation
# ---------------------------------------------------------------------------

class TestNonStreamingResponseValidation:
    """Validate that non-streaming Responses API output passes Response model validation."""

    def test_text_response_validates(self):
        """A plain text non-streaming response validates as a Response."""
        result = openai_result(content="Hello world", prompt_tokens=10, completion_tokens=5)
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ns1"
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.status == "completed"
        assert validated.model == "test-model"
        assert len(validated.output) >= 1
        assert validated.output[0].type == "message"

    def test_tool_call_response_validates(self):
        """A tool call non-streaming response validates."""
        result = openai_result(content=None, finish_reason="tool_calls")
        result["choices"][0]["message"]["tool_calls"] = [{
            "id": "call_abc",
            "type": "function",
            "function": {"name": "search", "arguments": '{"q":"test"}'},
        }]
        result["choices"][0]["message"]["content"] = None

        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ns2"
        )
        validated = sdk.Response.model_validate(resp)
        fc_items = [o for o in validated.output if o.type == "function_call"]
        assert len(fc_items) == 1
        assert fc_items[0].name == "search"
        assert fc_items[0].call_id == fc_items[0].id

    def test_reasoning_response_validates(self):
        """A reasoning non-streaming response validates."""
        result = openai_result(content="Answer", reasoning_content="I thought about it")
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ns3"
        )
        validated = sdk.Response.model_validate(resp)
        reasoning_items = [o for o in validated.output if o.type == "reasoning"]
        assert len(reasoning_items) == 1
        assert reasoning_items[0].summary[0].text == "I thought about it"

    def test_refusal_response_validates(self):
        """A refusal non-streaming response validates."""
        result = openai_result(content=None)
        result["choices"][0]["message"]["content"] = None
        result["choices"][0]["message"]["refusal"] = "I cannot help with that."
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ns4"
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.output[0].type == "message"
        refusals = [c for c in validated.output[0].content if c.type == "refusal"]
        assert len(refusals) == 1
        assert refusals[0].refusal == "I cannot help with that."

    def test_incomplete_response_validates(self):
        """A length-limited non-streaming response validates."""
        result = openai_result(content="truncated", finish_reason="length")
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ns5"
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.status == "incomplete"
        assert validated.incomplete_details is not None
        assert validated.incomplete_details.reason == "max_output_tokens"

    def test_empty_response_validates(self):
        """A response with no content still validates."""
        result = openai_result(content=None, finish_reason="stop")
        result["choices"][0]["message"]["content"] = None
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ns6"
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.status == "completed"
        assert len(validated.output) >= 1

    def test_usage_has_token_details(self):
        """Non-streaming usage includes required token detail sub-objects."""
        result = openai_result(prompt_tokens=20, completion_tokens=10)
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ns7"
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.usage.input_tokens == 20
        assert validated.usage.output_tokens == 10
        assert validated.usage.input_tokens_details.cached_tokens == 0
        assert validated.usage.output_tokens_details.reasoning_tokens == 0

    def test_metadata_passthrough_validates(self):
        """Metadata from request is preserved in the response."""
        result = openai_result()
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ns8",
            request_body={"metadata": {"key": "value"}}
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.metadata == {"key": "value"}

    def test_instructions_echo_validates(self):
        """Instructions from request are echoed in the response."""
        result = openai_result()
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ns9",
            request_body={"instructions": "Be brief."}
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.instructions == "Be brief."


# ---------------------------------------------------------------------------
# Empty / minimal stream paths
# ---------------------------------------------------------------------------

class TestMinimalStreamValidation:
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
        assert "response.created" in types
        assert "response.in_progress" in types
        assert "response.completed" in types

    @pytest.mark.asyncio
    async def test_done_only_stream_validates(self):
        """A stream with only data: [DONE] validates."""
        chunks = ["data: [DONE]\n\n"]
        events = await _run_stream_converter(chunks)
        validated = _validate_all_events(events)
        types = [t for t, _ in validated]
        assert "response.created" in types
        assert "response.completed" in types


# ---------------------------------------------------------------------------
# Combined paths
# ---------------------------------------------------------------------------

class TestCombinedPathValidation:
    """Validate streams with multiple content types."""

    @pytest.mark.asyncio
    async def test_reasoning_plus_text_plus_tool(self):
        """A stream with reasoning, text, and tool call validates fully."""
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

        # All three content types should have their events
        assert "response.reasoning_summary_text.delta" in types
        assert "response.output_text.delta" in types
        assert "response.function_call_arguments.done" in types
        assert "response.completed" in types

    @pytest.mark.asyncio
    async def test_request_body_fields_in_skeleton(self):
        """Request body fields (truncation, parallel_tool_calls, user, reasoning)
        are reflected in the skeleton and final response."""
        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "hi"}, "index": 0}]}),
            sse_chunk({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
            "data: [DONE]\n\n",
        ]
        request_body = {
            "truncation": "auto",
            "parallel_tool_calls": False,
            "user": "user_123",
            "reasoning": {"effort": "high"},
            "metadata": {"env": "test"},
            "instructions": "Be helpful.",
        }
        events = await _run_stream_converter(
            chunks, request_body=request_body
        )
        validated = _validate_all_events(events)

        # Check the created event's embedded response
        created = [m for t, m in validated if t == "response.created"][0]
        resp = created.response
        assert resp.truncation == "auto"
        assert resp.parallel_tool_calls is False
        assert resp.user == "user_123"
        assert resp.metadata == {"env": "test"}
        assert resp.instructions == "Be helpful."

    @pytest.mark.asyncio
    async def test_all_output_item_types_have_status(self):
        """Every output_item.added and output_item.done has a status field."""
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

        for t, m in validated:
            if t == "response.output_item.added":
                assert m.item.status in ("in_progress", "completed", "incomplete"), \
                    f"output_item.added has unexpected status: {m.item.status}"
            elif t == "response.output_item.done":
                assert m.item.status in ("in_progress", "completed", "incomplete"), \
                    f"output_item.done has unexpected status: {m.item.status}"


# ---------------------------------------------------------------------------
# Comprehensive non-streaming response variations
# ---------------------------------------------------------------------------

class TestNonStreamingMultipleOutputItems:
    """Validate non-streaming responses with multiple output item combinations."""

    def test_text_plus_function_call_plus_reasoning_validates(self):
        """Response with reasoning + text + function_call output items validates."""
        result = openai_result(content="I'll search for that.",
                               reasoning_content="Reasoning about the query.",
                               finish_reason="tool_calls")
        result["choices"][0]["message"]["tool_calls"] = [{
            "id": "call_abc",
            "type": "function",
            "function": {"name": "web_search", "arguments": '{"query":"test"}'},
        }]
        resp = responses_compat._build_responses_response(
            result, "gpt-4o", "resp_multi1"
        )
        validated = sdk.Response.model_validate(resp)

        types = [o.type for o in validated.output]
        assert "reasoning" in types
        assert "message" in types
        assert "function_call" in types
        assert len(validated.output) == 3

    def test_multiple_function_calls_validates(self):
        """Response with only function_call items (no text) validates."""
        result = openai_result(content=None, finish_reason="tool_calls")
        result["choices"][0]["message"]["content"] = None
        result["choices"][0]["message"]["tool_calls"] = [
            {"id": "call_1", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city":"NYC"}'}},
            {"id": "call_2", "type": "function",
             "function": {"name": "get_time", "arguments": '{"tz":"UTC"}'}},
        ]
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_multi2"
        )
        validated = sdk.Response.model_validate(resp)

        fc_items = [o for o in validated.output if o.type == "function_call"]
        assert len(fc_items) == 2
        names = {o.name for o in fc_items}
        assert names == {"get_weather", "get_time"}
        for fc in fc_items:
            assert fc.call_id == fc.id
            assert isinstance(fc.arguments, str)
            assert fc.status == "completed"


class TestNonStreamingAnnotations:
    """Validate non-streaming responses with text annotations."""

    def test_url_citation_annotations_validate(self):
        """Response with url_citation annotations validates."""
        result = openai_result(content="According to sources...")
        result["choices"][0]["message"]["annotations"] = [
            {
                "type": "url_citation",
                "url_citation": {
                    "start_index": 0,
                    "end_index": 25,
                    "url": "https://example.com",
                    "title": "Example Source",
                },
            }
        ]
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ann1"
        )
        validated = sdk.Response.model_validate(resp)

        msg_items = [o for o in validated.output if o.type == "message"]
        assert len(msg_items) == 1
        text_parts = [c for c in msg_items[0].content if c.type == "output_text"]
        assert len(text_parts) == 1
        assert len(text_parts[0].annotations) == 1
        ann = text_parts[0].annotations[0]
        assert ann.type == "url_citation"
        assert ann.url == "https://example.com"

    def test_perplexity_citations_validate(self):
        """Response with Perplexity-style citations validates."""
        result = openai_result(content="Here is the info.")
        result["choices"][0]["message"]["citations"] = [
            "https://example.com/page1",
            "https://example.com/page2",
        ]
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ann2"
        )
        validated = sdk.Response.model_validate(resp)

        msg_items = [o for o in validated.output if o.type == "message"]
        text_parts = [c for c in msg_items[0].content if c.type == "output_text"]
        assert len(text_parts[0].annotations) == 2


class TestNonStreamingRefusal:
    """Validate non-streaming responses with refusal content."""

    def test_refusal_response_validates(self):
        """Response with refusal validates with correct structure."""
        result = openai_result(content=None)
        result["choices"][0]["message"]["content"] = None
        result["choices"][0]["message"]["refusal"] = "I cannot assist with that request."
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ref1"
        )
        validated = sdk.Response.model_validate(resp)

        assert validated.status == "completed"
        msg_items = [o for o in validated.output if o.type == "message"]
        assert len(msg_items) == 1
        refusal_parts = [c for c in msg_items[0].content if c.type == "refusal"]
        assert len(refusal_parts) == 1
        assert refusal_parts[0].refusal == "I cannot assist with that request."

    def test_refusal_replaces_text_validates(self):
        """When refusal is set, it takes precedence over text content."""
        result = openai_result(content=None)
        result["choices"][0]["message"]["content"] = None
        result["choices"][0]["message"]["refusal"] = "Refused."
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ref2"
        )
        validated = sdk.Response.model_validate(resp)

        msg_items = [o for o in validated.output if o.type == "message"]
        assert len(msg_items) == 1
        text_parts = [c for c in msg_items[0].content if c.type == "output_text"]
        assert len(text_parts) == 0


class TestNonStreamingIncomplete:
    """Validate non-streaming responses with incomplete status."""

    def test_length_incomplete_validates(self):
        """Response with finish_reason=length produces valid incomplete response."""
        result = openai_result(content="truncated output", finish_reason="length")
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_inc1"
        )
        validated = sdk.Response.model_validate(resp)

        assert validated.status == "incomplete"
        assert validated.incomplete_details is not None
        assert validated.incomplete_details.reason == "max_output_tokens"
        assert validated.completed_at is None

    def test_content_filter_incomplete_validates(self):
        """Response with finish_reason=content_filter produces valid incomplete."""
        result = openai_result(content="filtered", finish_reason="content_filter")
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_inc2"
        )
        validated = sdk.Response.model_validate(resp)

        assert validated.status == "incomplete"
        assert validated.incomplete_details is not None
        assert validated.incomplete_details.reason == "content_filter"


class TestNonStreamingAllMetadata:
    """Validate non-streaming responses with all metadata fields."""

    def test_instructions_echo_validates(self):
        """Instructions from request echoed in response validates."""
        result = openai_result(content="Brief response.")
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_meta1",
            request_body={"instructions": "Be very brief and concise."}
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.instructions == "Be very brief and concise."

    def test_user_echo_validates(self):
        """User from request echoed in response validates."""
        result = openai_result(content="Response.")
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_meta2",
            request_body={"user": "user_abc123"}
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.user == "user_abc123"

    def test_reasoning_config_echo_validates(self):
        """Reasoning config from request echoed in response validates."""
        result = openai_result(content="Deep answer.")
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_meta3",
            request_body={"reasoning": {"effort": "high"}}
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.reasoning is not None

    def test_all_metadata_combined_validates(self):
        """Response with all metadata fields set validates."""
        result = openai_result(content="Full response.", prompt_tokens=500,
                               completion_tokens=200)
        resp = responses_compat._build_responses_response(
            result, "gpt-4o", "resp_meta4",
            request_body={
                "instructions": "Be helpful.",
                "user": "user_xyz",
                "metadata": {"env": "prod", "version": "2.0"},
                "reasoning": {"effort": "medium"},
                "truncation": "auto",
                "parallel_tool_calls": False,
            }
        )
        validated = sdk.Response.model_validate(resp)

        assert validated.instructions == "Be helpful."
        assert validated.user == "user_xyz"
        assert validated.metadata == {"env": "prod", "version": "2.0"}
        assert validated.truncation == "auto"
        assert validated.parallel_tool_calls is False
        assert validated.model == "gpt-4o"
        assert validated.status == "completed"
        assert validated.store is False
        assert validated.error is None


class TestNonStreamingCompletedAt:
    """Validate completed_at timestamp handling."""

    def test_completed_response_has_completed_at(self):
        """Completed responses have a completed_at timestamp."""
        result = openai_result(content="Done.")
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ts1"
        )
        validated = sdk.Response.model_validate(resp)

        assert validated.status == "completed"
        assert validated.completed_at is not None
        assert isinstance(validated.completed_at, (int, float))
        assert validated.completed_at > 0

    def test_incomplete_response_no_completed_at(self):
        """Incomplete responses have no completed_at timestamp."""
        result = openai_result(content="partial", finish_reason="length")
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ts2"
        )
        validated = sdk.Response.model_validate(resp)

        assert validated.status == "incomplete"
        assert validated.completed_at is None

    def test_created_at_present(self):
        """All responses have a created_at timestamp."""
        result = openai_result(content="any")
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_ts3"
        )
        validated = sdk.Response.model_validate(resp)

        assert validated.created_at is not None
        assert isinstance(validated.created_at, (int, float))
        assert validated.created_at > 0


class TestNonStreamingResponseStructure:
    """Validate the overall Response structure for completeness."""

    def test_response_object_field(self):
        """Response has object='response'."""
        result = openai_result()
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_struct1"
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.object == "response"

    def test_response_id_preserved(self):
        """Response ID from the call is preserved."""
        result = openai_result()
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_custom_id"
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.id == "resp_custom_id"

    def test_tools_empty_by_default(self):
        """Tools array is empty by default."""
        result = openai_result()
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_struct2"
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.tools == []

    def test_text_format_default(self):
        """Text format defaults to plain text."""
        result = openai_result()
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_struct3"
        )
        validated = sdk.Response.model_validate(resp)
        assert validated.text.format.type == "text"

    def test_usage_token_details_validates(self):
        """Usage includes input_tokens_details and output_tokens_details."""
        result = openai_result(prompt_tokens=100, completion_tokens=50)
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_struct4"
        )
        validated = sdk.Response.model_validate(resp)

        assert validated.usage.input_tokens == 100
        assert validated.usage.output_tokens == 50
        assert validated.usage.total_tokens == 150
        assert validated.usage.input_tokens_details.cached_tokens == 0
        assert validated.usage.output_tokens_details.reasoning_tokens == 0

    def test_reasoning_tokens_in_usage_validates(self):
        """Usage with reasoning tokens validates."""
        result = openai_result(content="answer", reasoning_content="thinking",
                               prompt_tokens=50, completion_tokens=30)
        result["usage"]["completion_tokens_details"] = {"reasoning_tokens": 20}
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_struct5"
        )
        validated = sdk.Response.model_validate(resp)

        assert validated.usage.output_tokens_details.reasoning_tokens == 20

    def test_reasoning_output_item_has_status(self):
        """Reasoning output items have status field."""
        result = openai_result(content="answer", reasoning_content="deep thought")
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_struct6"
        )
        validated = sdk.Response.model_validate(resp)

        reasoning_items = [o for o in validated.output if o.type == "reasoning"]
        assert len(reasoning_items) == 1
        assert reasoning_items[0].status == "completed"
        assert len(reasoning_items[0].summary) == 1
        assert reasoning_items[0].summary[0].type == "summary_text"
        assert reasoning_items[0].summary[0].text == "deep thought"

    def test_function_call_id_and_call_id_match(self):
        """Function call items have matching id and call_id."""
        result = openai_result(content=None, finish_reason="tool_calls")
        result["choices"][0]["message"]["content"] = None
        result["choices"][0]["message"]["tool_calls"] = [{
            "id": "call_match_test",
            "type": "function",
            "function": {"name": "fn", "arguments": "{}"},
        }]
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_struct7"
        )
        validated = sdk.Response.model_validate(resp)

        fc_items = [o for o in validated.output if o.type == "function_call"]
        assert len(fc_items) == 1
        assert fc_items[0].id == fc_items[0].call_id
