"""Tests for Boost's OpenAI Responses API compatibility layer."""

import json
import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, SRC_DIR)
os.chdir(SRC_DIR)

# Mock heavy modules that responses_compat imports but tests don't exercise.
for mod_name in ("mapper", "llm"):
    if mod_name not in sys.modules:
        stub = types.ModuleType(mod_name)
        if mod_name == "mapper":
            stub.list_downstream = None
            stub.resolve_request_config = None
            stub.is_direct_task = None
        if mod_name == "llm":
            stub.LLM = None
        sys.modules[mod_name] = stub

import responses_compat


# ---------------------------------------------------------------------------
# Input Conversion: _convert_input_to_messages
# ---------------------------------------------------------------------------


class TestConvertInputToMessages:
    def test_string_input(self):
        body = {"input": "hello"}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [{"role": "user", "content": "hello"}]

    def test_string_input_with_instructions(self):
        body = {"input": "hello", "instructions": "be concise"}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [
            {"role": "system", "content": "be concise"},
            {"role": "user", "content": "hello"},
        ]

    def test_none_input(self):
        body = {}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == []

    def test_instructions_only(self):
        body = {"instructions": "be nice"}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [{"role": "system", "content": "be nice"}]

    def test_array_of_strings(self):
        body = {"input": ["first", "second"]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
        ]

    def test_message_item_user(self):
        body = {"input": [
            {"type": "message", "role": "user", "content": "hi"}
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [{"role": "user", "content": "hi"}]

    def test_message_item_assistant(self):
        body = {"input": [
            {"type": "message", "role": "assistant", "content": "hello"}
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [{"role": "assistant", "content": "hello"}]

    def test_message_with_input_text_content_parts(self):
        body = {"input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "what is this?"},
                ],
            }
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        # Single text parts collapse to string
        assert msgs == [{"role": "user", "content": "what is this?"}]

    def test_message_with_input_image(self):
        body = {"input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "describe this"},
                    {"type": "input_image", "image_url": "https://example.com/img.png"},
                ],
            }
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert isinstance(msgs[0]["content"], list)
        assert msgs[0]["content"][0] == {"type": "text", "text": "describe this"}
        assert msgs[0]["content"][1]["type"] == "image_url"
        assert msgs[0]["content"][1]["image_url"]["url"] == "https://example.com/img.png"

    def test_function_call_output(self):
        body = {"input": [
            {
                "type": "function_call_output",
                "call_id": "call_123",
                "output": "result text",
            }
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [{
            "role": "tool",
            "tool_call_id": "call_123",
            "content": "result text",
        }]

    def test_multi_turn_conversation(self):
        body = {
            "instructions": "be helpful",
            "input": [
                {"type": "message", "role": "user", "content": "hi"},
                {"type": "message", "role": "assistant", "content": "hello"},
                {"type": "message", "role": "user", "content": "how are you?"},
            ],
        }
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 4
        assert msgs[0] == {"role": "system", "content": "be helpful"}
        assert msgs[1] == {"role": "user", "content": "hi"}
        assert msgs[2] == {"role": "assistant", "content": "hello"}
        assert msgs[3] == {"role": "user", "content": "how are you?"}

    def test_item_reference_skipped(self):
        body = {"input": [
            {"type": "item_reference", "id": "ref_123"},
            {"type": "message", "role": "user", "content": "hi"},
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "hi"


# ---------------------------------------------------------------------------
# Content part conversion
# ---------------------------------------------------------------------------


class TestConvertContentParts:
    def test_input_text(self):
        result = responses_compat._convert_content_parts([
            {"type": "input_text", "text": "hello"}
        ])
        assert result == "hello"

    def test_multiple_text_parts_collapse(self):
        result = responses_compat._convert_content_parts([
            {"type": "input_text", "text": "part1"},
            {"type": "input_text", "text": "part2"},
        ])
        assert result == "part1\npart2"

    def test_mixed_text_and_image(self):
        result = responses_compat._convert_content_parts([
            {"type": "input_text", "text": "look"},
            {"type": "input_image", "image_url": "https://x.com/i.png"},
        ])
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0] == {"type": "text", "text": "look"}
        assert result[1]["type"] == "image_url"

    def test_input_audio(self):
        result = responses_compat._convert_content_parts([
            {"type": "input_audio", "data": "base64data", "format": "mp3"},
        ])
        assert isinstance(result, list)
        assert result[0]["type"] == "input_audio"
        assert result[0]["input_audio"]["data"] == "base64data"

    def test_unknown_type_fallback(self):
        result = responses_compat._convert_content_parts([
            {"type": "unknown_widget", "text": "some text"},
        ])
        assert result == "some text"


# ---------------------------------------------------------------------------
# Tool conversion
# ---------------------------------------------------------------------------


class TestConvertTools:
    def test_function_tool(self):
        body = {"tools": [
            {
                "type": "function",
                "name": "get_weather",
                "description": "Gets weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            }
        ]}
        result = responses_compat._convert_tools(body)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "get_weather"
        assert result[0]["function"]["parameters"]["type"] == "object"

    def test_non_function_tools_skipped(self):
        body = {"tools": [
            {"type": "web_search"},
            {"type": "function", "name": "fn1", "description": "", "parameters": {}},
        ]}
        result = responses_compat._convert_tools(body)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "fn1"

    def test_no_tools(self):
        assert responses_compat._convert_tools({}) == []

    def test_empty_tools(self):
        assert responses_compat._convert_tools({"tools": []}) == []


# ---------------------------------------------------------------------------
# Tool choice conversion
# ---------------------------------------------------------------------------


class TestConvertToolChoice:
    def test_none(self):
        assert responses_compat._convert_tool_choice({}) is None

    def test_string_auto(self):
        assert responses_compat._convert_tool_choice({"tool_choice": "auto"}) == "auto"

    def test_string_none(self):
        assert responses_compat._convert_tool_choice({"tool_choice": "none"}) == "none"

    def test_string_required(self):
        assert responses_compat._convert_tool_choice({"tool_choice": "required"}) == "required"

    def test_function_dict(self):
        result = responses_compat._convert_tool_choice({
            "tool_choice": {"type": "function", "name": "get_weather"},
        })
        assert result == {"type": "function", "function": {"name": "get_weather"}}


# ---------------------------------------------------------------------------
# Build OpenAI body
# ---------------------------------------------------------------------------


class TestBuildOpenAIBody:
    def test_basic(self):
        body = {"model": "gpt-4o", "input": "hello"}
        result = responses_compat._build_openai_body(body)
        assert result["model"] == "gpt-4o"
        assert result["messages"] == [{"role": "user", "content": "hello"}]

    def test_max_output_tokens(self):
        body = {"model": "gpt-4o", "input": "hi", "max_output_tokens": 100}
        result = responses_compat._build_openai_body(body)
        assert result["max_tokens"] == 100

    def test_temperature_top_p(self):
        body = {"model": "gpt-4o", "input": "hi", "temperature": 0.5, "top_p": 0.9}
        result = responses_compat._build_openai_body(body)
        assert result["temperature"] == 0.5
        assert result["top_p"] == 0.9

    def test_stream_options(self):
        body = {"model": "gpt-4o", "input": "hi", "stream": True}
        result = responses_compat._build_openai_body(body)
        assert result["stream"] is True
        assert result["stream_options"] == {"include_usage": True}

    def test_tools_included(self):
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "tools": [
                {"type": "function", "name": "fn", "description": "d", "parameters": {}},
            ],
        }
        result = responses_compat._build_openai_body(body)
        assert len(result["tools"]) == 1

    def test_tool_choice_included(self):
        body = {"model": "gpt-4o", "input": "hi", "tool_choice": "auto"}
        result = responses_compat._build_openai_body(body)
        assert result["tool_choice"] == "auto"


# ---------------------------------------------------------------------------
# Response building
# ---------------------------------------------------------------------------


class TestBuildOutputItems:
    def test_text_only(self):
        openai_result = {
            "choices": [{"message": {"content": "hello world"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }
        output = responses_compat._build_output_items(openai_result)
        assert len(output) == 1
        assert output[0]["type"] == "message"
        assert output[0]["role"] == "assistant"
        assert output[0]["content"][0]["type"] == "output_text"
        assert output[0]["content"][0]["text"] == "hello world"

    def test_tool_calls(self):
        openai_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc",
                            "function": {"name": "get_weather", "arguments": '{"city":"NYC"}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        assert len(output) == 1
        assert output[0]["type"] == "function_call"
        assert output[0]["name"] == "get_weather"
        assert output[0]["arguments"] == '{"city":"NYC"}'
        assert output[0]["call_id"] == "call_abc"
        assert output[0]["id"] == "call_abc"

    def test_tool_call_id_and_call_id_match(self):
        """id and call_id must always be the same value."""
        openai_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"function": {"name": "fn", "arguments": "{}"}},
                    ],
                },
                "finish_reason": "tool_calls",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        assert output[0]["id"] == output[0]["call_id"]

    def test_text_and_tool_calls(self):
        openai_result = {
            "choices": [{
                "message": {
                    "content": "Let me check.",
                    "tool_calls": [
                        {"id": "call_1", "function": {"name": "fn", "arguments": "{}"}},
                    ],
                },
                "finish_reason": "tool_calls",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        assert len(output) == 2
        assert output[0]["type"] == "message"
        assert output[1]["type"] == "function_call"

    def test_empty_output_fallback(self):
        openai_result = {
            "choices": [{"message": {"content": None}, "finish_reason": "stop"}],
        }
        output = responses_compat._build_output_items(openai_result)
        assert len(output) == 1
        assert output[0]["type"] == "message"
        assert output[0]["content"][0]["text"] == ""


class TestMapStatus:
    def test_length(self):
        assert responses_compat._map_status("length") == "incomplete"

    def test_stop(self):
        assert responses_compat._map_status("stop") == "completed"

    def test_tool_calls(self):
        assert responses_compat._map_status("tool_calls") == "completed"


class TestBuildResponsesResponse:
    def test_basic(self):
        openai_result = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        }
        resp = responses_compat._build_responses_response(openai_result, "gpt-4o", "resp_123")
        assert resp["id"] == "resp_123"
        assert resp["object"] == "response"
        assert resp["model"] == "gpt-4o"
        assert resp["status"] == "completed"
        assert len(resp["output"]) == 1
        assert resp["usage"]["input_tokens"] == 3
        assert resp["usage"]["output_tokens"] == 1
        assert resp["usage"]["total_tokens"] == 4
        assert resp["error"] is None
        assert resp["incomplete_details"] is None

    def test_incomplete_status(self):
        openai_result = {
            "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        resp = responses_compat._build_responses_response(openai_result, "gpt-4o", "resp_456")
        assert resp["status"] == "incomplete"
        assert resp["incomplete_details"]["reason"] == "max_output_tokens"

    def test_usage_has_token_details(self):
        openai_result = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        resp = responses_compat._build_responses_response(openai_result, "gpt-4o", "resp_td")
        usage = resp["usage"]
        assert "input_tokens_details" in usage
        assert usage["input_tokens_details"]["cached_tokens"] == 0
        assert "output_tokens_details" in usage
        assert usage["output_tokens_details"]["reasoning_tokens"] == 0


# ---------------------------------------------------------------------------
# _make_usage
# ---------------------------------------------------------------------------


class TestMakeUsage:
    def test_defaults(self):
        u = responses_compat._make_usage()
        assert u["input_tokens"] == 0
        assert u["output_tokens"] == 0
        assert u["total_tokens"] == 0
        assert u["input_tokens_details"]["cached_tokens"] == 0
        assert u["output_tokens_details"]["reasoning_tokens"] == 0

    def test_custom_values(self):
        u = responses_compat._make_usage(input_tokens=10, output_tokens=5)
        assert u["total_tokens"] == 15

    def test_explicit_total(self):
        u = responses_compat._make_usage(input_tokens=10, output_tokens=5, total_tokens=20)
        assert u["total_tokens"] == 20


# ---------------------------------------------------------------------------
# Error response
# ---------------------------------------------------------------------------


class TestResponsesError:
    def test_400(self):
        resp = responses_compat._responses_error(400, "bad request")
        body = json.loads(resp.body.decode())
        assert resp.status_code == 400
        assert body["error"]["type"] == "invalid_request_error"
        assert body["error"]["message"] == "bad request"

    def test_500(self):
        resp = responses_compat._responses_error(500, "oops")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "server_error"

    def test_custom_type(self):
        resp = responses_compat._responses_error(422, "msg", error_type="custom_type")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "custom_type"

    def test_error_code(self):
        resp = responses_compat._responses_error(400, "msg", error_code="model_not_found")
        body = json.loads(resp.body.decode())
        assert body["error"]["code"] == "model_not_found"


# ---------------------------------------------------------------------------
# Streaming conversion
# ---------------------------------------------------------------------------


def _parse_sse_events(raw_events):
    """Parse raw SSE strings into (event_type, data_dict) tuples."""
    parsed = []
    for raw in raw_events:
        lines = raw.strip().split("\n")
        event_type = None
        data_str = None
        for line in lines:
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
        if event_type and data_str:
            parsed.append((event_type, json.loads(data_str)))
    return parsed


class TestResponsesStreamConverter:
    @pytest.mark.asyncio
    async def test_text_only_stream(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"Hello"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":" world"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ):
            events.append(event)

        event_types = [e.split("\n")[0].replace("event: ", "") for e in events]

        assert "response.created" in event_types
        assert "response.in_progress" in event_types
        assert "response.output_item.added" in event_types
        assert "response.content_part.added" in event_types
        assert "response.output_text.delta" in event_types
        assert "response.output_text.done" in event_types
        assert "response.content_part.done" in event_types
        assert "response.output_item.done" in event_types
        assert "response.completed" in event_types

    @pytest.mark.asyncio
    async def test_in_progress_event_after_created(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_ip"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # response.in_progress must be present
        assert "response.in_progress" in event_types

        # It must come immediately after response.created
        created_idx = event_types.index("response.created")
        assert event_types[created_idx + 1] == "response.in_progress"

        # It carries the same skeleton response with in_progress status
        _, data = parsed[created_idx + 1]
        assert data["type"] == "response.in_progress"
        assert "sequence_number" in data
        assert data["response"]["status"] == "in_progress"
        assert data["response"]["id"] == "resp_ip"

    @pytest.mark.asyncio
    async def test_in_progress_event_validates_sdk(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"x"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_ipv"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        in_progress = [d for t, d in parsed if t == "response.in_progress"]
        assert len(in_progress) == 1
        try:
            import openai.types.responses as r
            r.ResponseInProgressEvent.model_validate(in_progress[0])
        except ImportError:
            pytest.skip("openai SDK not installed")

    @pytest.mark.asyncio
    async def test_all_events_have_sequence_number(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_seq"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        for event_type, data in parsed:
            if event_type in ("response.created", "response.completed"):
                assert "sequence_number" in data, f"{event_type} missing sequence_number"
            else:
                assert "sequence_number" in data, f"{event_type} missing sequence_number"

    @pytest.mark.asyncio
    async def test_sequence_numbers_monotonically_increase(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"A"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"B"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_mono"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        seq_nums = [d.get("sequence_number") for _, d in parsed]
        for i in range(1, len(seq_nums)):
            assert seq_nums[i] > seq_nums[i - 1], \
                f"sequence_number not monotonically increasing: {seq_nums}"

    @pytest.mark.asyncio
    async def test_text_delta_has_logprobs(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_lp"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        deltas = [(t, d) for t, d in parsed if t == "response.output_text.delta"]
        assert len(deltas) > 0
        for _, data in deltas:
            assert "logprobs" in data
            assert data["logprobs"] == []

    @pytest.mark.asyncio
    async def test_text_done_event_emitted(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"AB"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_td"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        done_events = [(t, d) for t, d in parsed if t == "response.output_text.done"]
        assert len(done_events) == 1
        _, data = done_events[0]
        assert data["text"] == "AB"
        assert data["logprobs"] == []

    @pytest.mark.asyncio
    async def test_text_deltas_accumulated(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"A"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"B"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "test-model", "resp_acc"
        ):
            events.append(event)

        # Find the content_part.done event
        done_events = [e for e in events if "response.content_part.done" in e]
        assert len(done_events) == 1
        data = json.loads(done_events[0].split("data: ", 1)[1])
        assert data["part"]["text"] == "AB"

    @pytest.mark.asyncio
    async def test_tool_call_stream(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"fn","arguments":""}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"k\\":"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"v\\"}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "test-model", "resp_tool"
        ):
            events.append(event)

        event_types = [e.split("\n")[0].replace("event: ", "") for e in events]
        assert "response.output_item.added" in event_types
        assert "response.function_call_arguments.delta" in event_types
        assert "response.function_call_arguments.done" in event_types
        assert "response.output_item.done" in event_types

        # Find the output_item.done for the tool
        tool_done = [e for e in events if "response.output_item.done" in e and "function_call" in e]
        assert len(tool_done) == 1
        data = json.loads(tool_done[0].split("data: ", 1)[1])
        assert data["item"]["name"] == "fn"
        assert data["item"]["arguments"] == '{"k":"v"}'

    @pytest.mark.asyncio
    async def test_function_call_arguments_done_event(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"fn","arguments":"{\\"a\\":1}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_fcd"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        done_events = [(t, d) for t, d in parsed if t == "response.function_call_arguments.done"]
        assert len(done_events) == 1
        _, data = done_events[0]
        assert data["arguments"] == '{"a":1}'
        assert data["name"] == "fn"
        assert data["item_id"] == "call_1"

    @pytest.mark.asyncio
    async def test_text_then_tool_call(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"Let me check."},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_x","function":{"name":"search","arguments":"{}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "test", "resp_tt"
        ):
            events.append(event)

        event_types = [e.split("\n")[0].replace("event: ", "") for e in events]

        # Should have text events, then close text, then tool events
        assert event_types.count("response.output_item.added") == 2
        assert event_types.count("response.output_item.done") == 2
        # Text done before tool starts
        assert "response.output_text.done" in event_types

    @pytest.mark.asyncio
    async def test_empty_stream(self):
        async def mock_stream():
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "test", "resp_empty"
        ):
            events.append(event)

        event_types = [e.split("\n")[0].replace("event: ", "") for e in events]
        assert event_types[0] == "response.created"
        assert event_types[-1] == "response.completed"

    @pytest.mark.asyncio
    async def test_usage_in_completed_event(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"ok"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":3,"total_tokens":13}}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_u"
        ):
            events.append(event)

        completed = [e for e in events if "response.completed" in e]
        assert len(completed) == 1
        data = json.loads(completed[0].split("data: ", 1)[1])
        usage = data["response"]["usage"]
        assert usage["input_tokens"] == 10
        assert usage["output_tokens"] == 3
        assert "input_tokens_details" in usage
        assert "output_tokens_details" in usage

    @pytest.mark.asyncio
    async def test_mid_stream_error(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"start"},"index":0}]}\n\n'
            raise RuntimeError("connection lost")

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_err"
        ):
            events.append(event)

        event_types = [e.split("\n")[0].replace("event: ", "") for e in events]
        assert "response.completed" in event_types

        # Should have error text in a delta
        error_deltas = [e for e in events if "Stream error" in e]
        assert len(error_deltas) > 0

    @pytest.mark.asyncio
    async def test_created_event_has_response_skeleton(self):
        async def mock_stream():
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_skel"
        ):
            events.append(event)

        created = events[0]
        data = json.loads(created.split("data: ", 1)[1])
        assert data["type"] == "response.created"
        assert "sequence_number" in data
        assert data["response"]["id"] == "resp_skel"
        assert data["response"]["object"] == "response"
        assert data["response"]["model"] == "gpt-4o"
        assert data["response"]["status"] == "in_progress"
        assert data["response"]["output"] == []
        # Usage must have token detail sub-objects
        usage = data["response"]["usage"]
        assert "input_tokens_details" in usage
        assert "output_tokens_details" in usage


# ---------------------------------------------------------------------------
# Chunk utilities
# ---------------------------------------------------------------------------


class TestChunkUtilities:
    def test_get_chunk_content(self):
        chunk = {"choices": [{"delta": {"content": "text"}}]}
        assert responses_compat._get_chunk_content(chunk) == "text"

    def test_get_chunk_content_empty(self):
        chunk = {"choices": [{"delta": {}}]}
        assert responses_compat._get_chunk_content(chunk) == ""

    def test_get_chunk_tool_calls(self):
        tc = [{"index": 0, "id": "c1", "function": {"name": "fn"}}]
        chunk = {"choices": [{"delta": {"tool_calls": tc}}]}
        assert responses_compat._get_chunk_tool_calls(chunk) == tc

    def test_get_chunk_usage_present(self):
        chunk = {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        assert responses_compat._get_chunk_usage(chunk)["prompt_tokens"] == 10

    def test_get_chunk_usage_absent(self):
        chunk = {}
        result = responses_compat._get_chunk_usage(chunk)
        assert result["prompt_tokens"] == 0


# ---------------------------------------------------------------------------
# SDK compatibility: validate events against OpenAI SDK models
# ---------------------------------------------------------------------------


class TestSDKCompatibility:
    """Validate that emitted events can be parsed by the OpenAI Python SDK models."""

    def _try_validate(self, model_cls, data):
        """Attempt SDK model validation; skip if openai is not installed."""
        try:
            import openai.types.responses as r
            cls = getattr(r, model_cls)
            cls.model_validate(data)
        except ImportError:
            pytest.skip("openai SDK not installed")

    @pytest.mark.asyncio
    async def test_created_event_validates(self):
        async def mock_stream():
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_v1"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        created = [d for t, d in parsed if t == "response.created"]
        assert len(created) == 1
        self._try_validate("ResponseCreatedEvent", created[0])

    @pytest.mark.asyncio
    async def test_completed_event_validates(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"ok"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_v2"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        completed = [d for t, d in parsed if t == "response.completed"]
        assert len(completed) == 1
        self._try_validate("ResponseCompletedEvent", completed[0])

    @pytest.mark.asyncio
    async def test_text_delta_event_validates(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_v3"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        assert len(deltas) > 0
        self._try_validate("ResponseTextDeltaEvent", deltas[0])

    @pytest.mark.asyncio
    async def test_text_done_event_validates(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_v4"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        done = [d for t, d in parsed if t == "response.output_text.done"]
        assert len(done) == 1
        self._try_validate("ResponseTextDoneEvent", done[0])

    @pytest.mark.asyncio
    async def test_output_item_added_message_validates(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_v5"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        added = [d for t, d in parsed if t == "response.output_item.added"]
        assert len(added) > 0
        self._try_validate("ResponseOutputItemAddedEvent", added[0])

    @pytest.mark.asyncio
    async def test_function_call_arguments_done_validates(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"fn","arguments":"{\\"a\\":1}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_v6"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        done = [d for t, d in parsed if t == "response.function_call_arguments.done"]
        assert len(done) == 1
        self._try_validate("ResponseFunctionCallArgumentsDoneEvent", done[0])

    @pytest.mark.asyncio
    async def test_content_part_added_validates(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_v7"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        added = [d for t, d in parsed if t == "response.content_part.added"]
        assert len(added) > 0
        self._try_validate("ResponseContentPartAddedEvent", added[0])

    @pytest.mark.asyncio
    async def test_content_part_done_validates(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_v8"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        done = [d for t, d in parsed if t == "response.content_part.done"]
        assert len(done) > 0
        self._try_validate("ResponseContentPartDoneEvent", done[0])

    @pytest.mark.asyncio
    async def test_non_streaming_response_validates(self):
        """Non-streaming Response object validates against SDK model."""
        openai_result = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }
        resp = responses_compat._build_responses_response(openai_result, "gpt-4o", "resp_ns")
        try:
            import openai.types.responses as r
            r.Response.model_validate(resp)
        except ImportError:
            pytest.skip("openai SDK not installed")


# ---------------------------------------------------------------------------
# Integration tests using TestClient
# ---------------------------------------------------------------------------


class TestResponsesRouteIntegration:
    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch):
        """Set up a test FastAPI app with the responses router."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        monkeypatch.setattr(responses_compat.config, "BOOST_AUTH", [])

        app = FastAPI()
        app.include_router(responses_compat.responses_compatible_routes)
        self.client = TestClient(app)

    def test_missing_model_returns_400(self):
        resp = self.client.post("/v1/responses", json={"input": "hi"})
        assert resp.status_code == 400
        assert "model" in resp.json()["error"]["message"]

    def test_missing_input_returns_400(self):
        resp = self.client.post("/v1/responses", json={"model": "gpt-4o"})
        assert resp.status_code == 400
        assert "input" in resp.json()["error"]["message"]

    def test_invalid_json_returns_400(self):
        resp = self.client.post(
            "/v1/responses",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    def test_non_streaming_response(self, monkeypatch):
        mock_result = {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1000,
            "model": "gpt-4o",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }

        async def mock_list_downstream():
            return []

        mock_llm = MagicMock()
        mock_llm.workflow = None
        mock_llm.boost_params = {}

        async def mock_serve():
            async def gen():
                yield f'data: {json.dumps(mock_result)}\n\n'
                yield 'data: [DONE]\n\n'
            return gen()

        async def mock_consume(stream):
            return mock_result

        mock_llm.serve = mock_serve
        mock_llm.consume_stream = mock_consume

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(responses_compat.mapper, "resolve_request_config", lambda body: {})
        monkeypatch.setattr(responses_compat.mapper, "is_direct_task", lambda proxy: False)
        monkeypatch.setattr(responses_compat.llm_mod, "LLM", lambda **kw: mock_llm)

        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hello",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "response"
        assert body["status"] == "completed"
        assert len(body["output"]) == 1
        assert body["output"][0]["type"] == "message"
        assert body["output"][0]["content"][0]["text"] == "hi"
        assert body["usage"]["input_tokens"] == 5
        assert "input_tokens_details" in body["usage"]
        assert "output_tokens_details" in body["usage"]

    def test_streaming_response(self, monkeypatch):
        async def mock_list_downstream():
            return []

        mock_llm = MagicMock()
        mock_llm.workflow = None
        mock_llm.boost_params = {}

        async def mock_serve():
            async def gen():
                yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
                yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n'
                yield 'data: [DONE]\n\n'
            return gen()

        mock_llm.serve = mock_serve

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(responses_compat.mapper, "resolve_request_config", lambda body: {})
        monkeypatch.setattr(responses_compat.mapper, "is_direct_task", lambda proxy: False)
        monkeypatch.setattr(responses_compat.llm_mod, "LLM", lambda **kw: mock_llm)

        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hello",
            "stream": True,
        })

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        text = resp.text
        assert "response.created" in text
        assert "response.in_progress" in text
        assert "response.output_text.delta" in text
        assert "response.output_text.done" in text
        assert "response.completed" in text

    def test_direct_task_passthrough(self, monkeypatch):
        mock_result = {
            "choices": [{"message": {"content": "title"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

        async def mock_list_downstream():
            return []

        mock_llm = MagicMock()
        mock_llm.workflow = None
        mock_llm.boost_params = {}

        async def mock_chat_completion():
            return mock_result

        mock_llm.chat_completion = mock_chat_completion

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(responses_compat.mapper, "resolve_request_config", lambda body: {})
        monkeypatch.setattr(responses_compat.mapper, "is_direct_task", lambda proxy: True)
        monkeypatch.setattr(responses_compat.llm_mod, "LLM", lambda **kw: mock_llm)

        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hello",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "response"
        assert body["output"][0]["content"][0]["text"] == "title"

    def test_mapper_value_error(self, monkeypatch):
        async def mock_list_downstream():
            return []

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(
            responses_compat.mapper,
            "resolve_request_config",
            MagicMock(side_effect=ValueError("Unable to proxy request without a model specifier")),
        )

        resp = self.client.post("/v1/responses", json={
            "model": "unknown-model",
            "input": "hi",
        })

        assert resp.status_code == 400

    def test_auth_required(self, monkeypatch):
        monkeypatch.setattr(responses_compat.config, "BOOST_AUTH", ["sk-test"])

        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hello",
        })

        assert resp.status_code == 403

    def test_auth_accepted(self, monkeypatch):
        monkeypatch.setattr(responses_compat.config, "BOOST_AUTH", ["sk-test"])

        async def mock_list_downstream():
            return []

        mock_result = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

        mock_llm = MagicMock()
        mock_llm.workflow = None
        mock_llm.boost_params = {}

        async def mock_serve():
            async def gen():
                yield f'data: {json.dumps(mock_result)}\n\n'
                yield 'data: [DONE]\n\n'
            return gen()

        async def mock_consume(stream):
            return mock_result

        mock_llm.serve = mock_serve
        mock_llm.consume_stream = mock_consume

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(responses_compat.mapper, "resolve_request_config", lambda body: {})
        monkeypatch.setattr(responses_compat.mapper, "is_direct_task", lambda proxy: False)
        monkeypatch.setattr(responses_compat.llm_mod, "LLM", lambda **kw: mock_llm)

        resp = self.client.post(
            "/v1/responses",
            json={"model": "gpt-4o", "input": "hello"},
            headers={"Authorization": "Bearer sk-test"},
        )

        assert resp.status_code == 200
