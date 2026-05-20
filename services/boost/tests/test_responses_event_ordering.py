"""Integration tests for Responses API streaming event ordering.

Verifies the EXACT sequence of event types emitted by
``_responses_stream_converter`` for all major response scenarios.
Each test asserts the full ordered list of event type strings,
ensuring the streaming converter produces a spec-compliant lifecycle.
"""

import json

import pytest

import responses_compat
from helpers import parse_responses_sse_events as _parse_sse_events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chunk(data: dict) -> str:
    """Build an SSE data line from a dict, matching LLM.serve() output."""
    return f"data: {json.dumps(data)}\n\n"


def _text_delta(text: str) -> str:
    return _chunk({"choices": [{"delta": {"content": text}, "index": 0}]})


def _reasoning_delta(text: str) -> str:
    return _chunk({"choices": [{"delta": {"reasoning_content": text}, "index": 0}]})


def _refusal_delta(text: str) -> str:
    return _chunk({"choices": [{"delta": {"refusal": text}, "index": 0}]})


def _tool_call_start(index: int, call_id: str, name: str, args: str = "") -> str:
    return _chunk({"choices": [{"delta": {"tool_calls": [
        {"index": index, "id": call_id, "function": {"name": name, "arguments": args}}
    ]}, "index": 0}]})


def _tool_call_args(index: int, args: str) -> str:
    return _chunk({"choices": [{"delta": {"tool_calls": [
        {"index": index, "function": {"arguments": args}}
    ]}, "index": 0}]})


def _finish(reason: str = "stop", prompt_tokens: int = 5, completion_tokens: int = 5) -> str:
    return _chunk({
        "choices": [{"delta": {}, "index": 0, "finish_reason": reason}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    })


DONE = "data: [DONE]\n\n"


def _event_types(events):
    """Extract just the event type strings from parsed SSE events."""
    return [t for t, _ in _parse_sse_events(events)]


def _event_pairs(events):
    """Return (event_type, data_dict) tuples from parsed SSE events."""
    return _parse_sse_events(events)


async def _collect(stream_gen):
    """Collect all SSE strings from an async generator."""
    result = []
    async for event in stream_gen:
        result.append(event)
    return result


# ---------------------------------------------------------------------------
# a) Simple text response
# ---------------------------------------------------------------------------


class TestSimpleTextEventOrdering:
    """Verify exact event ordering for a plain text streaming response."""

    @pytest.mark.asyncio
    async def test_simple_text_full_sequence(self):
        """Single text response must produce the canonical lifecycle:
        response.created -> response.in_progress ->
        response.output_item.added -> response.content_part.added ->
        response.output_text.delta(s) ->
        response.output_text.done -> response.content_part.done ->
        response.output_item.done -> response.completed
        """
        async def mock_stream():
            yield _text_delta("Hello")
            yield _text_delta(" world")
            yield _finish("stop", 5, 2)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types == [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.content_part.added",
            "response.output_text.delta",
            "response.output_text.delta",
            "response.output_text.done",
            "response.content_part.done",
            "response.output_item.done",
            "response.completed",
        ]

    @pytest.mark.asyncio
    async def test_simple_text_single_delta(self):
        """Single delta still produces the full lifecycle."""
        async def mock_stream():
            yield _text_delta("Hi")
            yield _finish("stop", 1, 1)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types == [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.content_part.added",
            "response.output_text.delta",
            "response.output_text.done",
            "response.content_part.done",
            "response.output_item.done",
            "response.completed",
        ]

    @pytest.mark.asyncio
    async def test_simple_text_many_deltas(self):
        """Many deltas produce many delta events but the envelope is constant."""
        async def mock_stream():
            for c in "abcdef":
                yield _text_delta(c)
            yield _finish("stop", 1, 6)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        expected = [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.content_part.added",
        ] + ["response.output_text.delta"] * 6 + [
            "response.output_text.done",
            "response.content_part.done",
            "response.output_item.done",
            "response.completed",
        ]
        assert types == expected

    @pytest.mark.asyncio
    async def test_text_done_contains_full_text(self):
        """output_text.done must contain the concatenation of all deltas."""
        async def mock_stream():
            yield _text_delta("Hello")
            yield _text_delta(" world")
            yield _finish("stop", 1, 2)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        text_done = [d for t, d in pairs if t == "response.output_text.done"]
        assert len(text_done) == 1
        assert text_done[0]["text"] == "Hello world"


# ---------------------------------------------------------------------------
# b) Tool call response
# ---------------------------------------------------------------------------


class TestToolCallEventOrdering:
    """Verify exact event ordering for tool call (function_call) responses."""

    @pytest.mark.asyncio
    async def test_single_tool_call_full_sequence(self):
        """Tool call: created -> in_progress -> output_item.added(function_call) ->
        function_call_arguments.delta(s) -> function_call_arguments.done ->
        output_item.done -> response.completed
        """
        async def mock_stream():
            yield _tool_call_start(0, "call_abc", "get_weather", "")
            yield _tool_call_args(0, '{"city":"NYC"}')
            yield _finish("tool_calls", 10, 5)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types == [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
            "response.output_item.done",
            "response.completed",
        ]

    @pytest.mark.asyncio
    async def test_tool_call_multiple_arg_deltas(self):
        """Arguments arriving in multiple chunks produce multiple delta events."""
        async def mock_stream():
            yield _tool_call_start(0, "call_x", "fn", "")
            yield _tool_call_args(0, '{"a"')
            yield _tool_call_args(0, ":1}")
            yield _finish("tool_calls", 1, 3)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types == [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.function_call_arguments.delta",
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
            "response.output_item.done",
            "response.completed",
        ]

    @pytest.mark.asyncio
    async def test_tool_call_done_has_full_arguments(self):
        """function_call_arguments.done contains the fully concatenated arguments."""
        async def mock_stream():
            yield _tool_call_start(0, "call_t", "fn", '{"k"')
            yield _tool_call_args(0, ":1}")
            yield _finish("tool_calls", 1, 2)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        done = [d for t, d in pairs if t == "response.function_call_arguments.done"]
        assert len(done) == 1
        assert done[0]["arguments"] == '{"k":1}'

    @pytest.mark.asyncio
    async def test_tool_call_output_item_types(self):
        """output_item.added and output_item.done must both have type=function_call."""
        async def mock_stream():
            yield _tool_call_start(0, "call_z", "fn", "{}")
            yield _finish("tool_calls", 1, 1)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        added = [d for t, d in pairs if t == "response.output_item.added"]
        done = [d for t, d in pairs if t == "response.output_item.done"]
        assert len(added) == 1
        assert added[0]["item"]["type"] == "function_call"
        assert len(done) == 1
        assert done[0]["item"]["type"] == "function_call"


# ---------------------------------------------------------------------------
# c) Reasoning + text
# ---------------------------------------------------------------------------


class TestReasoningPlusTextEventOrdering:
    """Verify exact event ordering when reasoning precedes text output."""

    @pytest.mark.asyncio
    async def test_reasoning_then_text_full_sequence(self):
        """Reasoning followed by text:
        created -> in_progress ->
        output_item.added(reasoning) -> reasoning_summary_part.added ->
        reasoning_summary_text.delta(s) ->
        reasoning_summary_text.done -> reasoning_summary_part.done ->
        output_item.done(reasoning) ->
        output_item.added(message) -> content_part.added ->
        output_text.delta(s) ->
        output_text.done -> content_part.done ->
        output_item.done(message) -> response.completed
        """
        async def mock_stream():
            yield _reasoning_delta("Think")
            yield _reasoning_delta("ing...")
            yield _text_delta("Answer")
            yield _finish("stop", 5, 3)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types == [
            "response.created",
            "response.in_progress",
            # Reasoning item
            "response.output_item.added",
            "response.reasoning_summary_part.added",
            "response.reasoning_summary_text.delta",
            "response.reasoning_summary_text.delta",
            # Close reasoning
            "response.reasoning_summary_text.done",
            "response.reasoning_summary_part.done",
            "response.output_item.done",
            # Text item
            "response.output_item.added",
            "response.content_part.added",
            "response.output_text.delta",
            # Close text
            "response.output_text.done",
            "response.content_part.done",
            "response.output_item.done",
            "response.completed",
        ]

    @pytest.mark.asyncio
    async def test_reasoning_output_indices(self):
        """Reasoning is output_index=0, text is output_index=1."""
        async def mock_stream():
            yield _reasoning_delta("R")
            yield _text_delta("T")
            yield _finish("stop", 1, 2)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        added = [d for t, d in pairs if t == "response.output_item.added"]
        assert len(added) == 2
        # Reasoning comes first at index 0
        assert added[0]["output_index"] == 0
        assert added[0]["item"]["type"] == "reasoning"
        # Text comes second at index 1
        assert added[1]["output_index"] == 1
        assert added[1]["item"]["type"] == "message"

    @pytest.mark.asyncio
    async def test_reasoning_only_no_text(self):
        """Reasoning with no text still gets properly closed."""
        async def mock_stream():
            yield _reasoning_delta("thinking...")
            yield _finish("stop", 1, 1)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types == [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.reasoning_summary_part.added",
            "response.reasoning_summary_text.delta",
            "response.reasoning_summary_text.done",
            "response.reasoning_summary_part.done",
            "response.output_item.done",
            "response.completed",
        ]


# ---------------------------------------------------------------------------
# d) Refusal
# ---------------------------------------------------------------------------


class TestRefusalEventOrdering:
    """Verify exact event ordering for refusal responses."""

    @pytest.mark.asyncio
    async def test_refusal_full_sequence(self):
        """Refusal: created -> in_progress -> output_item.added ->
        content_part.added(refusal) -> refusal.delta(s) ->
        refusal.done -> content_part.done -> output_item.done ->
        response.completed
        """
        async def mock_stream():
            yield _refusal_delta("I cannot")
            yield _refusal_delta(" help with that.")
            yield _finish("stop", 3, 5)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types == [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.content_part.added",
            "response.refusal.delta",
            "response.refusal.delta",
            "response.refusal.done",
            "response.content_part.done",
            "response.output_item.done",
            "response.completed",
        ]

    @pytest.mark.asyncio
    async def test_refusal_done_contains_full_text(self):
        """refusal.done must contain the concatenated refusal text."""
        async def mock_stream():
            yield _refusal_delta("No ")
            yield _refusal_delta("way")
            yield _finish("stop", 1, 1)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        done = [d for t, d in pairs if t == "response.refusal.done"]
        assert len(done) == 1
        assert done[0]["refusal"] == "No way"

    @pytest.mark.asyncio
    async def test_refusal_content_part_type(self):
        """content_part.added for refusal must have type=refusal."""
        async def mock_stream():
            yield _refusal_delta("denied")
            yield _finish("stop", 1, 1)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        part_added = [d for t, d in pairs if t == "response.content_part.added"]
        assert len(part_added) == 1
        assert part_added[0]["part"]["type"] == "refusal"


# ---------------------------------------------------------------------------
# e) Multiple tools
# ---------------------------------------------------------------------------


class TestMultipleToolsEventOrdering:
    """Verify exact event ordering when two tool calls are emitted."""

    @pytest.mark.asyncio
    async def test_two_tool_calls_same_chunk(self):
        """Two parallel tool calls arriving in the same chunk each get their lifecycle."""
        async def mock_stream():
            # Both tool IDs arrive in the same chunk
            yield _chunk({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_a", "function": {"name": "fn1", "arguments": ""}},
                {"index": 1, "id": "call_b", "function": {"name": "fn2", "arguments": ""}},
            ]}, "index": 0}]})
            # Args for both
            yield _chunk({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": '{"x":1}'}},
                {"index": 1, "function": {"arguments": '{"y":2}'}},
            ]}, "index": 0}]})
            yield _finish("tool_calls", 1, 2)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types == [
            "response.created",
            "response.in_progress",
            # Tool 1 added (index 0)
            "response.output_item.added",
            # Tool 2 added (index 1)
            "response.output_item.added",
            # Tool 1 arg delta
            "response.function_call_arguments.delta",
            # Tool 2 arg delta
            "response.function_call_arguments.delta",
            # Tool 1 close
            "response.function_call_arguments.done",
            "response.output_item.done",
            # Tool 2 close
            "response.function_call_arguments.done",
            "response.output_item.done",
            "response.completed",
        ]

    @pytest.mark.asyncio
    async def test_two_sequential_tool_calls(self):
        """Tool calls arriving in separate chunks still produce correct ordering."""
        async def mock_stream():
            yield _tool_call_start(0, "call_first", "fn1", '{"a":1}')
            yield _tool_call_start(1, "call_second", "fn2", '{"b":2}')
            yield _finish("tool_calls", 1, 2)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types == [
            "response.created",
            "response.in_progress",
            # Tool 1 emitted immediately with accumulated args
            "response.output_item.added",
            "response.function_call_arguments.delta",
            # Tool 2 emitted next
            "response.output_item.added",
            "response.function_call_arguments.delta",
            # Both closed in order at end
            "response.function_call_arguments.done",
            "response.output_item.done",
            "response.function_call_arguments.done",
            "response.output_item.done",
            "response.completed",
        ]

    @pytest.mark.asyncio
    async def test_multiple_tools_each_have_unique_output_index(self):
        """Each tool call must have a distinct output_index."""
        async def mock_stream():
            yield _tool_call_start(0, "call_m1", "fn1", "{}")
            yield _tool_call_start(1, "call_m2", "fn2", "{}")
            yield _finish("tool_calls", 1, 2)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        added = [d for t, d in pairs if t == "response.output_item.added"]
        assert len(added) == 2
        assert added[0]["output_index"] != added[1]["output_index"]

        done = [d for t, d in pairs if t == "response.output_item.done"]
        assert len(done) == 2
        assert done[0]["output_index"] != done[1]["output_index"]


# ---------------------------------------------------------------------------
# f) Incomplete response (finish_reason: length)
# ---------------------------------------------------------------------------


class TestIncompleteResponseEventOrdering:
    """Verify that finish_reason=length produces response.incomplete."""

    @pytest.mark.asyncio
    async def test_incomplete_full_sequence(self):
        """Text truncated by length: ends with response.incomplete."""
        async def mock_stream():
            yield _text_delta("Partial")
            yield _finish("length", 5, 1)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types == [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.content_part.added",
            "response.output_text.delta",
            "response.output_text.done",
            "response.content_part.done",
            "response.output_item.done",
            "response.incomplete",
        ]

    @pytest.mark.asyncio
    async def test_incomplete_has_details(self):
        """response.incomplete event must include incomplete_details.reason."""
        async def mock_stream():
            yield _text_delta("x")
            yield _finish("length", 1, 1)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        incomplete = [d for t, d in pairs if t == "response.incomplete"]
        assert len(incomplete) == 1
        assert incomplete[0]["response"]["incomplete_details"]["reason"] == "max_output_tokens"

    @pytest.mark.asyncio
    async def test_content_filter_incomplete(self):
        """finish_reason=content_filter also produces response.incomplete."""
        async def mock_stream():
            yield _text_delta("x")
            yield _finish("content_filter", 1, 1)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types[-1] == "response.incomplete"

        pairs = _event_pairs(events)
        incomplete = [d for t, d in pairs if t == "response.incomplete"]
        assert incomplete[0]["response"]["incomplete_details"]["reason"] == "content_filter"


# ---------------------------------------------------------------------------
# g) Failed response (mid-stream error)
# ---------------------------------------------------------------------------


class TestFailedResponseEventOrdering:
    """Verify that mid-stream errors produce response.failed."""

    @pytest.mark.asyncio
    async def test_exception_during_stream_produces_failed(self):
        """Exception in the stream produces error text + response.failed."""
        async def mock_stream():
            yield _text_delta("start")
            raise Exception("connection reset")

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types[0] == "response.created"
        assert types[1] == "response.in_progress"
        assert types[-1] == "response.failed"

    @pytest.mark.asyncio
    async def test_failed_response_structure(self):
        """response.failed event must have status=failed in the response."""
        async def mock_stream():
            raise Exception("boom")
            yield  # make it an async generator

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        failed = [d for t, d in pairs if t == "response.failed"]
        assert len(failed) == 1
        assert failed[0]["response"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_backend_error_429_produces_failed(self):
        """BackendError with 429 status produces response.failed."""
        from llm import BackendError

        async def mock_stream():
            yield _text_delta("Hi")
            raise BackendError(429, "rate limited")

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types[-1] == "response.failed"

        pairs = _event_pairs(events)
        # There should be an error delta mentioning rate limit
        error_deltas = [d for t, d in pairs if t == "response.output_text.delta"
                        and "rate limit" in d.get("delta", "").lower()]
        assert len(error_deltas) >= 1

    @pytest.mark.asyncio
    async def test_failed_without_prior_content_creates_text_item(self):
        """Error on empty stream still wraps error in a proper text item."""
        async def mock_stream():
            raise Exception("fail immediately")
            yield  # make it a generator

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert "response.output_item.added" in types
        assert "response.content_part.added" in types
        assert "response.output_text.delta" in types
        assert types[-1] == "response.failed"

    @pytest.mark.asyncio
    async def test_failed_with_prior_text_closes_text_item(self):
        """Error after text content: text item closed, error appended, then failed."""
        async def mock_stream():
            yield _text_delta("partial")
            raise RuntimeError("kaboom")

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        # Must have text delta, then error delta, then proper closures
        assert types[0] == "response.created"
        assert types[1] == "response.in_progress"
        assert "response.output_text.delta" in types
        assert "response.output_text.done" in types
        assert "response.content_part.done" in types
        assert "response.output_item.done" in types
        assert types[-1] == "response.failed"


# ---------------------------------------------------------------------------
# h) Text + tool call (mixed)
# ---------------------------------------------------------------------------


class TestTextPlusToolEventOrdering:
    """Verify ordering when text content precedes a tool call."""

    @pytest.mark.asyncio
    async def test_text_then_tool_full_sequence(self):
        """Text followed by tool call: text item fully closed before tool opens."""
        async def mock_stream():
            yield _text_delta("Let me search")
            yield _tool_call_start(0, "call_s", "search", '{"q":"test"}')
            yield _finish("tool_calls", 5, 5)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types == [
            "response.created",
            "response.in_progress",
            # Text item lifecycle
            "response.output_item.added",
            "response.content_part.added",
            "response.output_text.delta",
            # Text item closes before tool opens
            "response.output_text.done",
            "response.content_part.done",
            "response.output_item.done",
            # Tool item lifecycle
            "response.output_item.added",
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
            "response.output_item.done",
            "response.completed",
        ]


# ---------------------------------------------------------------------------
# i) Reasoning + text + tool call (all three)
# ---------------------------------------------------------------------------


class TestReasoningTextToolEventOrdering:
    """Verify ordering for reasoning -> text -> tool call sequences."""

    @pytest.mark.asyncio
    async def test_reasoning_text_tool_full_sequence(self):
        """All three output types in sequence: each fully closed before the next opens."""
        async def mock_stream():
            yield _reasoning_delta("Let me think")
            yield _text_delta("I will search")
            yield _tool_call_start(0, "call_rt", "search", "{}")
            yield _finish("tool_calls", 1, 3)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types == [
            "response.created",
            "response.in_progress",
            # Reasoning
            "response.output_item.added",
            "response.reasoning_summary_part.added",
            "response.reasoning_summary_text.delta",
            "response.reasoning_summary_text.done",
            "response.reasoning_summary_part.done",
            "response.output_item.done",
            # Text
            "response.output_item.added",
            "response.content_part.added",
            "response.output_text.delta",
            "response.output_text.done",
            "response.content_part.done",
            "response.output_item.done",
            # Tool
            "response.output_item.added",
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
            "response.output_item.done",
            "response.completed",
        ]


# ---------------------------------------------------------------------------
# j) Empty / no-content stream
# ---------------------------------------------------------------------------


class TestEmptyStreamEventOrdering:
    """Verify event ordering when the stream has no content."""

    @pytest.mark.asyncio
    async def test_finish_reason_only_stream(self):
        """Stream with only a finish_reason chunk: just the envelope events."""
        async def mock_stream():
            yield _finish("stop", 5, 0)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types == [
            "response.created",
            "response.in_progress",
            "response.completed",
        ]


# ---------------------------------------------------------------------------
# k) Sequence number monotonicity
# ---------------------------------------------------------------------------


class TestSequenceNumberOrdering:
    """Verify that sequence_number is strictly monotonically increasing."""

    @pytest.mark.asyncio
    async def test_sequence_numbers_monotonic_text(self):
        """All events in a text stream have increasing sequence numbers."""
        async def mock_stream():
            yield _text_delta("a")
            yield _text_delta("b")
            yield _finish("stop", 1, 2)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        seqs = [d["sequence_number"] for _, d in pairs]
        for i in range(1, len(seqs)):
            assert seqs[i] > seqs[i - 1], (
                f"Sequence number not monotonic at event {i}: "
                f"{seqs[i - 1]} >= {seqs[i]}"
            )

    @pytest.mark.asyncio
    async def test_sequence_numbers_start_at_zero(self):
        """Sequence numbering starts at 0."""
        async def mock_stream():
            yield _text_delta("x")
            yield _finish("stop", 1, 1)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        assert pairs[0][1]["sequence_number"] == 0

    @pytest.mark.asyncio
    async def test_sequence_numbers_complex_scenario(self):
        """Reasoning + text + tool: all events still have strictly increasing seq numbers."""
        async def mock_stream():
            yield _reasoning_delta("R")
            yield _text_delta("T")
            yield _tool_call_start(0, "call_q", "fn", "{}")
            yield _finish("tool_calls", 1, 3)
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        seqs = [d["sequence_number"] for _, d in pairs]
        for i in range(1, len(seqs)):
            assert seqs[i] > seqs[i - 1]


# ---------------------------------------------------------------------------
# l) Terminal event correctness
# ---------------------------------------------------------------------------


class TestTerminalEvents:
    """Verify the correct terminal event is used for each scenario."""

    @pytest.mark.asyncio
    async def test_stop_produces_completed(self):
        """finish_reason=stop -> response.completed."""
        async def mock_stream():
            yield _text_delta("x")
            yield _finish("stop")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))
        assert _event_types(events)[-1] == "response.completed"

    @pytest.mark.asyncio
    async def test_tool_calls_produces_completed(self):
        """finish_reason=tool_calls -> response.completed (tools are not incomplete)."""
        async def mock_stream():
            yield _tool_call_start(0, "call_tc", "fn", "{}")
            yield _finish("tool_calls")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))
        assert _event_types(events)[-1] == "response.completed"

    @pytest.mark.asyncio
    async def test_length_produces_incomplete(self):
        """finish_reason=length -> response.incomplete."""
        async def mock_stream():
            yield _text_delta("x")
            yield _finish("length")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))
        assert _event_types(events)[-1] == "response.incomplete"

    @pytest.mark.asyncio
    async def test_error_produces_failed(self):
        """Exception during streaming -> response.failed."""
        async def mock_stream():
            raise RuntimeError("kaboom")
            yield  # make it a generator

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))
        assert _event_types(events)[-1] == "response.failed"

    @pytest.mark.asyncio
    async def test_completed_has_completed_at(self):
        """response.completed event must set completed_at on the response."""
        async def mock_stream():
            yield _text_delta("x")
            yield _finish("stop")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        completed = [d for t, d in pairs if t == "response.completed"]
        assert len(completed) == 1
        assert "completed_at" in completed[0]["response"]
        assert isinstance(completed[0]["response"]["completed_at"], int)

    @pytest.mark.asyncio
    async def test_incomplete_has_no_completed_at(self):
        """response.incomplete must NOT have completed_at."""
        async def mock_stream():
            yield _text_delta("x")
            yield _finish("length")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        incomplete = [d for t, d in pairs if t == "response.incomplete"]
        assert len(incomplete) == 1
        assert "completed_at" not in incomplete[0]["response"]


# ---------------------------------------------------------------------------
# m) Created/in_progress response skeleton
# ---------------------------------------------------------------------------


class TestEnvelopeEvents:
    """Verify that created and in_progress events have proper structure."""

    @pytest.mark.asyncio
    async def test_created_has_response_with_in_progress_status(self):
        """response.created event's embedded response has status=in_progress."""
        async def mock_stream():
            yield _text_delta("x")
            yield _finish("stop")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        created = [d for t, d in pairs if t == "response.created"]
        assert len(created) == 1
        assert created[0]["response"]["status"] == "in_progress"
        assert created[0]["response"]["model"] == "gpt-4o"
        assert created[0]["response"]["id"] == "resp_test"

    @pytest.mark.asyncio
    async def test_in_progress_follows_created(self):
        """response.in_progress must always be the second event."""
        async def mock_stream():
            yield _text_delta("x")
            yield _finish("stop")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        types = _event_types(events)
        assert types[0] == "response.created"
        assert types[1] == "response.in_progress"

    @pytest.mark.asyncio
    async def test_created_echoes_request_body_metadata(self):
        """response.created event should echo metadata from the request body."""
        async def mock_stream():
            yield _text_delta("x")
            yield _finish("stop")
            yield DONE

        request_body = {
            "model": "gpt-4o",
            "input": "test",
            "metadata": {"custom_key": "custom_value"},
            "instructions": "be brief",
            "user": "test_user",
        }

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test", request_body=request_body
        ))

        pairs = _event_pairs(events)
        created = [d for t, d in pairs if t == "response.created"]
        resp = created[0]["response"]
        assert resp["metadata"] == {"custom_key": "custom_value"}
        assert resp["instructions"] == "be brief"
        assert resp["user"] == "test_user"


# ---------------------------------------------------------------------------
# n) Output item status transitions
# ---------------------------------------------------------------------------


class TestOutputItemStatusTransitions:
    """Verify that output items transition from in_progress to completed."""

    @pytest.mark.asyncio
    async def test_text_item_status_in_progress_to_completed(self):
        """output_item.added has status=in_progress, output_item.done has status=completed."""
        async def mock_stream():
            yield _text_delta("x")
            yield _finish("stop")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        added = [d for t, d in pairs if t == "response.output_item.added"]
        done = [d for t, d in pairs if t == "response.output_item.done"]
        assert added[0]["item"]["status"] == "in_progress"
        assert done[0]["item"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_tool_item_status_transition(self):
        """Tool call output_item transitions in_progress -> completed."""
        async def mock_stream():
            yield _tool_call_start(0, "call_st", "fn", "{}")
            yield _finish("tool_calls")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        added = [d for t, d in pairs if t == "response.output_item.added"
                 and d["item"]["type"] == "function_call"]
        done = [d for t, d in pairs if t == "response.output_item.done"
                and d["item"]["type"] == "function_call"]
        assert added[0]["item"]["status"] == "in_progress"
        assert done[0]["item"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_reasoning_item_status_transition(self):
        """Reasoning output_item transitions in_progress -> completed."""
        async def mock_stream():
            yield _reasoning_delta("think")
            yield _finish("stop")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        added = [d for t, d in pairs if t == "response.output_item.added"
                 and d["item"]["type"] == "reasoning"]
        done = [d for t, d in pairs if t == "response.output_item.done"
                and d["item"]["type"] == "reasoning"]
        assert added[0]["item"]["status"] == "in_progress"
        assert done[0]["item"]["status"] == "completed"


# ---------------------------------------------------------------------------
# o) Consistency: every added item gets a done
# ---------------------------------------------------------------------------


class TestAddedDonePairing:
    """Every output_item.added must have a matching output_item.done."""

    @pytest.mark.asyncio
    async def test_text_added_done_pairing(self):
        """Single text item: 1 added, 1 done."""
        async def mock_stream():
            yield _text_delta("x")
            yield _finish("stop")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        added_count = sum(1 for t, _ in pairs if t == "response.output_item.added")
        done_count = sum(1 for t, _ in pairs if t == "response.output_item.done")
        assert added_count == done_count == 1

    @pytest.mark.asyncio
    async def test_reasoning_text_tool_all_paired(self):
        """Reasoning + text + tool: 3 added, 3 done."""
        async def mock_stream():
            yield _reasoning_delta("R")
            yield _text_delta("T")
            yield _tool_call_start(0, "call_p", "fn", "{}")
            yield _finish("tool_calls")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        added_count = sum(1 for t, _ in pairs if t == "response.output_item.added")
        done_count = sum(1 for t, _ in pairs if t == "response.output_item.done")
        assert added_count == done_count == 3

    @pytest.mark.asyncio
    async def test_content_part_added_done_pairing(self):
        """Every content_part.added has a matching content_part.done."""
        async def mock_stream():
            yield _text_delta("x")
            yield _finish("stop")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        cp_added = sum(1 for t, _ in pairs if t == "response.content_part.added")
        cp_done = sum(1 for t, _ in pairs if t == "response.content_part.done")
        assert cp_added == cp_done == 1

    @pytest.mark.asyncio
    async def test_two_tools_added_done_pairing(self):
        """Two tool calls: 2 added, 2 done, 2 function_call_arguments.done."""
        async def mock_stream():
            yield _chunk({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_aa", "function": {"name": "fn1", "arguments": "{}"}},
                {"index": 1, "id": "call_bb", "function": {"name": "fn2", "arguments": "{}"}},
            ]}, "index": 0}]})
            yield _finish("tool_calls")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        added = sum(1 for t, _ in pairs if t == "response.output_item.added")
        done = sum(1 for t, _ in pairs if t == "response.output_item.done")
        args_done = sum(1 for t, _ in pairs if t == "response.function_call_arguments.done")
        assert added == done == args_done == 2

    @pytest.mark.asyncio
    async def test_refusal_content_part_pairing(self):
        """Refusal: 1 content_part.added, 1 content_part.done, 1 output_item.added, 1 output_item.done."""
        async def mock_stream():
            yield _refusal_delta("no")
            yield _finish("stop")
            yield DONE

        events = await _collect(responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ))

        pairs = _event_pairs(events)
        assert sum(1 for t, _ in pairs if t == "response.output_item.added") == 1
        assert sum(1 for t, _ in pairs if t == "response.output_item.done") == 1
        assert sum(1 for t, _ in pairs if t == "response.content_part.added") == 1
        assert sum(1 for t, _ in pairs if t == "response.content_part.done") == 1
