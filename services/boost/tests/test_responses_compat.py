"""Tests for Boost's OpenAI Responses API compatibility layer."""

import json
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# Module stubs for mapper/llm are registered in conftest.py

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

    def test_web_search_preview_mapped_to_function(self):
        body = {"tools": [
            {"type": "web_search_preview"},
            {"type": "function", "name": "fn1", "description": "", "parameters": {}},
        ]}
        result = responses_compat._convert_tools(body)
        assert len(result) == 2
        ws = result[0]
        assert ws["type"] == "function"
        assert ws["function"]["name"] == "web_search"
        assert "query" in ws["function"]["parameters"]["properties"]
        assert result[1]["function"]["name"] == "fn1"

    def test_web_search_type_mapped_to_function(self):
        body = {"tools": [{"type": "web_search"}]}
        result = responses_compat._convert_tools(body)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "web_search"

    def test_web_search_deduplicated(self):
        body = {"tools": [
            {"type": "web_search_preview"},
            {"type": "web_search"},
        ]}
        result = responses_compat._convert_tools(body)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "web_search"

    def test_file_search_skipped_with_warning(self):
        body = {"tools": [
            {"type": "file_search"},
            {"type": "function", "name": "fn1", "description": "", "parameters": {}},
        ]}
        result = responses_compat._convert_tools(body)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "fn1"

    def test_code_interpreter_skipped_with_warning(self):
        body = {"tools": [{"type": "code_interpreter"}]}
        result = responses_compat._convert_tools(body)
        assert len(result) == 0

    def test_unsupported_builtin_tools_logged(self):
        import logging
        body = {"tools": [
            {"type": "file_search"},
            {"type": "code_interpreter"},
        ]}
        with unittest.mock.patch.object(responses_compat.logger, "warning") as mock_warn:
            responses_compat._convert_tools(body)
            assert mock_warn.call_count == 2
            call_args = [c[0][1] for c in mock_warn.call_args_list]
            assert "file_search" in call_args
            assert "code_interpreter" in call_args

    def test_web_search_tool_has_correct_schema(self):
        body = {"tools": [{"type": "web_search_preview"}]}
        result = responses_compat._convert_tools(body)
        ws = result[0]
        assert ws["function"]["parameters"]["type"] == "object"
        assert ws["function"]["parameters"]["required"] == ["query"]
        assert ws["function"]["parameters"]["properties"]["query"]["type"] == "string"
        assert ws["function"]["description"]  # non-empty

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

    def test_web_search_preview_choice_maps_to_function(self):
        result = responses_compat._convert_tool_choice({
            "tool_choice": {"type": "web_search_preview"},
        })
        assert result == {"type": "function", "function": {"name": "web_search"}}

    def test_web_search_choice_maps_to_function(self):
        result = responses_compat._convert_tool_choice({
            "tool_choice": {"type": "web_search"},
        })
        assert result == {"type": "function", "function": {"name": "web_search"}}

    def test_file_search_choice_falls_back_to_auto(self):
        result = responses_compat._convert_tool_choice({
            "tool_choice": {"type": "file_search"},
        })
        assert result == "auto"

    def test_code_interpreter_choice_falls_back_to_auto(self):
        result = responses_compat._convert_tool_choice({
            "tool_choice": {"type": "code_interpreter"},
        })
        assert result == "auto"

    def test_unsupported_tool_choice_logged(self):
        with unittest.mock.patch.object(responses_compat.logger, "warning") as mock_warn:
            responses_compat._convert_tool_choice({
                "tool_choice": {"type": "file_search"},
            })
            mock_warn.assert_called_once()
            assert "file_search" in mock_warn.call_args[0][1]


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

    def test_web_search_preview_tool_included_in_body(self):
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "tools": [{"type": "web_search_preview"}],
        }
        result = responses_compat._build_openai_body(body)
        assert len(result["tools"]) == 1
        assert result["tools"][0]["function"]["name"] == "web_search"

    def test_web_search_preview_with_function_tools(self):
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "tools": [
                {"type": "web_search_preview"},
                {"type": "function", "name": "fn", "description": "d", "parameters": {}},
            ],
        }
        result = responses_compat._build_openai_body(body)
        assert len(result["tools"]) == 2
        names = [t["function"]["name"] for t in result["tools"]]
        assert "web_search" in names
        assert "fn" in names

    def test_web_search_tool_choice_in_body(self):
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "tools": [{"type": "web_search_preview"}],
            "tool_choice": {"type": "web_search_preview"},
        }
        result = responses_compat._build_openai_body(body)
        assert result["tool_choice"] == {"type": "function", "function": {"name": "web_search"}}


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
# Tool ID Normalization (Responses API)
# ---------------------------------------------------------------------------


class TestResponsesToolIdNormalization:
    """Verify tool IDs are normalized to call_ prefix in Responses API output."""

    def test_build_output_items_normalizes_toolu_prefix(self):
        """Backend returns toolu_-prefixed IDs; should become call_ in Responses output."""
        openai_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "toolu_abc123",
                        "function": {"name": "search", "arguments": '{"q": "test"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        tc = [o for o in output if o["type"] == "function_call"][0]
        assert tc["id"] == "call_abc123"
        assert tc["call_id"] == "call_abc123"

    def test_build_output_items_preserves_call_prefix(self):
        """Backend returns call_-prefixed IDs; should remain unchanged."""
        openai_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_xyz789",
                        "function": {"name": "fetch", "arguments": '{}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        tc = [o for o in output if o["type"] == "function_call"][0]
        assert tc["id"] == "call_xyz789"
        assert tc["call_id"] == "call_xyz789"

    def test_build_output_items_normalizes_chatcmpl_prefix(self):
        """Backend returns chatcmpl-prefixed IDs; should become call_."""
        openai_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "chatcmpl-abc",
                        "function": {"name": "fn", "arguments": '{}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        tc = [o for o in output if o["type"] == "function_call"][0]
        assert tc["id"] == "call_abc"
        assert tc["call_id"] == "call_abc"

    def test_build_output_items_missing_id_generates_call(self):
        """Tool call with no id should generate a call_-prefixed ID."""
        openai_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "function": {"name": "fn", "arguments": '{}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        tc = [o for o in output if o["type"] == "function_call"][0]
        assert tc["id"].startswith("call_")
        assert tc["call_id"].startswith("call_")
        assert tc["id"] == tc["call_id"]

    def test_build_responses_response_tool_ids_normalized(self):
        """Full response builder should normalize tool IDs to call_ prefix."""
        openai_result = {
            "choices": [{
                "message": {
                    "content": "Let me search",
                    "tool_calls": [{
                        "id": "toolu_resp123",
                        "function": {"name": "search", "arguments": '{"q": "hello"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        response = responses_compat._build_responses_response(openai_result, "gpt-4o", "resp_test")
        tc_items = [o for o in response["output"] if o["type"] == "function_call"]
        assert len(tc_items) == 1
        assert tc_items[0]["id"] == "call_resp123"
        assert tc_items[0]["call_id"] == "call_resp123"


class TestResponsesToolIdNormalizationInStreaming:
    """Verify tool IDs are normalized to call_ in Responses streaming responses."""

    @pytest.mark.asyncio
    async def test_stream_normalizes_toolu_prefix_to_call(self):
        """Streaming tool call with toolu_ prefix should emit call_ in output_item.added."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"toolu_stream1","function":{"name":"search","arguments":""}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"q\\":\\"test\\"}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":5,"completion_tokens":10,"total_tokens":15}}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        added = [d for t, d in parsed if t == "response.output_item.added"
                 and d.get("item", {}).get("type") == "function_call"]
        assert len(added) == 1
        assert added[0]["item"]["id"] == "call_stream1"
        assert added[0]["item"]["call_id"] == "call_stream1"

        # Also check done event
        done = [d for t, d in parsed if t == "response.output_item.done"
                and d.get("item", {}).get("type") == "function_call"]
        assert len(done) == 1
        assert done[0]["item"]["id"] == "call_stream1"
        assert done[0]["item"]["call_id"] == "call_stream1"

    @pytest.mark.asyncio
    async def test_stream_preserves_call_prefix(self):
        """Streaming tool call with call_ prefix should remain unchanged."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_existing","function":{"name":"fn","arguments":"{}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        added = [d for t, d in parsed if t == "response.output_item.added"
                 and d.get("item", {}).get("type") == "function_call"]
        assert len(added) == 1
        assert added[0]["item"]["id"] == "call_existing"

    @pytest.mark.asyncio
    async def test_stream_function_call_arguments_events_use_normalized_id(self):
        """Function call argument delta and done events should use normalized IDs."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"toolu_argtest","function":{"name":"fn","arguments":"{\\"a\\":1}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_test"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        deltas = [d for t, d in parsed if t == "response.function_call_arguments.delta"]
        assert len(deltas) >= 1
        assert deltas[0]["item_id"] == "call_argtest"

        dones = [d for t, d in parsed if t == "response.function_call_arguments.done"]
        assert len(dones) == 1
        assert dones[0]["item_id"] == "call_argtest"


class TestResponsesToolIdRoundTrip:
    """Verify round-trip ID handling: backend -> response -> client -> request."""

    def test_round_trip_toolu_to_call_and_back(self):
        """Backend sends toolu_ -> output has call_ -> client sends call_ in
        function_call_output -> passes through correctly to backend."""
        # Step 1: Backend returns toolu_-prefixed tool call
        openai_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "toolu_roundtrip1",
                        "function": {"name": "search", "arguments": '{}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        }
        output = responses_compat._build_output_items(openai_result)
        tc = [o for o in output if o["type"] == "function_call"][0]
        call_id = tc["call_id"]
        assert call_id == "call_roundtrip1"

        # Step 2: Client sends function_call_output with the call_ ID
        body = {
            "input": [
                {"type": "function_call_output", "call_id": call_id, "output": "result"},
            ],
        }
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs[0]["tool_call_id"] == "call_roundtrip1"

    def test_function_call_output_normalizes_toolu_prefix(self):
        """function_call_output with toolu_ call_id should be normalized to call_."""
        body = {
            "input": [
                {"type": "function_call_output", "call_id": "toolu_abc", "output": "result"},
            ],
        }
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs[0]["tool_call_id"] == "call_abc"


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

        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])

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
        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", ["sk-test"])

        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hello",
        })

        assert resp.status_code == 403

    def test_auth_accepted(self, monkeypatch):
        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", ["sk-test"])

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


# ---------------------------------------------------------------------------
# Request-ID header tests
# ---------------------------------------------------------------------------


class TestResponsesRequestIdHeader:
    """Verify that the request-id header is present on all response paths."""

    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])

        app = FastAPI()
        app.include_router(responses_compat.responses_compatible_routes)
        self.client = TestClient(app)

    def _assert_request_id(self, resp):
        """Assert request-id header is present and has correct format."""
        assert "request-id" in resp.headers, "Missing request-id header"
        rid = resp.headers["request-id"]
        assert rid.startswith("req_"), f"request-id should start with req_, got: {rid}"

    def test_request_id_on_non_streaming_response(self, monkeypatch):
        mock_result = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
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
        self._assert_request_id(resp)

    def test_request_id_on_streaming_response(self, monkeypatch):
        async def mock_list_downstream():
            return []

        mock_llm = MagicMock()
        mock_llm.workflow = None
        mock_llm.boost_params = {}

        async def mock_serve():
            async def gen():
                yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
                yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
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
        self._assert_request_id(resp)

    def test_request_id_on_direct_task_response(self, monkeypatch):
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
        self._assert_request_id(resp)

    def test_request_id_on_validation_error(self):
        resp = self.client.post("/v1/responses", json={"input": "hi"})
        assert resp.status_code == 400
        self._assert_request_id(resp)

    def test_request_id_on_invalid_json_error(self):
        resp = self.client.post(
            "/v1/responses",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400
        self._assert_request_id(resp)

    def test_request_id_on_mapper_error(self, monkeypatch):
        async def mock_list_downstream():
            return []

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(
            responses_compat.mapper,
            "resolve_request_config",
            MagicMock(side_effect=ValueError("Unable to proxy")),
        )

        resp = self.client.post("/v1/responses", json={
            "model": "unknown",
            "input": "hi",
        })

        assert resp.status_code == 400
        self._assert_request_id(resp)

    def test_request_id_unique_per_request(self, monkeypatch):
        """Each request should get a unique request-id."""
        resp1 = self.client.post("/v1/responses", json={"input": "hi"})
        resp2 = self.client.post("/v1/responses", json={"input": "hi"})
        rid1 = resp1.headers.get("request-id")
        rid2 = resp2.headers.get("request-id")
        assert rid1 != rid2, "Each request must get a unique request-id"


# ---------------------------------------------------------------------------
# Edge case: Input conversion
# ---------------------------------------------------------------------------


class TestInputConversionEdgeCases:
    """Edge cases for _convert_input_to_messages."""

    def test_empty_array_input(self):
        """Empty input array should produce no messages (besides instructions if any)."""
        body = {"input": []}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == []

    def test_empty_array_with_instructions(self):
        """Empty input array with instructions should produce only the system message."""
        body = {"input": [], "instructions": "be nice"}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 1
        assert msgs[0] == {"role": "system", "content": "be nice"}

    def test_whitespace_only_string_input(self):
        """Whitespace-only string input should be passed through as a user message."""
        body = {"input": "   "}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 1
        assert msgs[0] == {"role": "user", "content": "   "}

    def test_newline_only_string_input(self):
        body = {"input": "\n\n"}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 1
        assert msgs[0] == {"role": "user", "content": "\n\n"}

    def test_message_content_as_string(self):
        """Message item with content as a string (not array) should work."""
        body = {"input": [
            {"type": "message", "role": "user", "content": "hello"}
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [{"role": "user", "content": "hello"}]

    def test_message_content_as_array_of_parts(self):
        """Message item with content as array of content parts should work."""
        body = {"input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "first"},
                    {"type": "input_text", "text": "second"},
                ],
            }
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 1
        # Multiple text parts collapse to a single string
        assert msgs[0]["content"] == "first\nsecond"

    def test_mixed_interleaved_items(self):
        """Messages, function_call_output, and strings interleaved correctly."""
        body = {"input": [
            {"type": "message", "role": "user", "content": "What is the weather?"},
            {"type": "message", "role": "assistant", "content": "Let me check."},
            {"type": "function_call_output", "call_id": "call_1", "output": "Sunny, 72F"},
            {"type": "message", "role": "user", "content": "Thanks!"},
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 4
        assert msgs[0] == {"role": "user", "content": "What is the weather?"}
        assert msgs[1] == {"role": "assistant", "content": "Let me check."}
        assert msgs[2] == {"role": "tool", "tool_call_id": "call_1", "content": "Sunny, 72F"}
        assert msgs[3] == {"role": "user", "content": "Thanks!"}

    def test_function_call_output_string_output(self):
        """function_call_output with output as a string should convert correctly."""
        body = {"input": [
            {"type": "function_call_output", "call_id": "call_42", "output": "result data"},
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [{"role": "tool", "tool_call_id": "call_42", "content": "result data"}]

    def test_function_call_output_empty_output(self):
        """function_call_output with empty/missing output should default to empty string."""
        body = {"input": [
            {"type": "function_call_output", "call_id": "call_99"},
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [{"role": "tool", "tool_call_id": "call_99", "content": ""}]

    def test_function_call_output_missing_call_id(self):
        """function_call_output with missing call_id should default to empty string."""
        body = {"input": [
            {"type": "function_call_output", "output": "some result"},
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [{"role": "tool", "tool_call_id": "", "content": "some result"}]

    def test_non_dict_non_string_item(self):
        """Non-dict, non-string items in the input array should be stringified."""
        body = {"input": [42, True]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "content": "42"}
        assert msgs[1] == {"role": "user", "content": "True"}

    def test_unknown_item_type_silently_skipped(self):
        """Items with unrecognized type should be silently skipped."""
        body = {"input": [
            {"type": "unknown_item_type", "data": "stuff"},
            {"type": "message", "role": "user", "content": "hi"},
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "hi"

    def test_empty_content_parts_list(self):
        """Message with empty content parts list should produce empty string content."""
        body = {"input": [
            {"type": "message", "role": "user", "content": []},
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 1
        # Empty parts list collapses to empty string
        assert msgs[0]["content"] == ""

    def test_non_list_non_string_input(self):
        """Input as neither string, list, nor None should be stringified."""
        body = {"input": 42}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [{"role": "user", "content": "42"}]

    def test_empty_instructions(self):
        """Empty string instructions should not produce a system message."""
        body = {"input": "hi", "instructions": ""}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"


# ---------------------------------------------------------------------------
# Edge case: Response conversion
# ---------------------------------------------------------------------------


class TestResponseConversionEdgeCases:
    """Edge cases for response building."""

    def test_empty_string_content(self):
        """Backend returns empty string content -> should produce empty output_text."""
        openai_result = {
            "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 0, "total_tokens": 5},
        }
        output = responses_compat._build_output_items(openai_result)
        assert len(output) == 1
        assert output[0]["type"] == "message"
        assert output[0]["content"][0]["text"] == ""

    def test_none_content(self):
        """Backend returns None content -> should produce empty output_text fallback."""
        openai_result = {
            "choices": [{"message": {"content": None}, "finish_reason": "stop"}],
        }
        output = responses_compat._build_output_items(openai_result)
        assert len(output) == 1
        assert output[0]["type"] == "message"
        assert output[0]["content"][0]["text"] == ""

    def test_multiple_tool_calls(self):
        """Backend returns multiple tool calls -> each becomes a function_call item."""
        openai_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "call_a", "function": {"name": "fn_1", "arguments": '{"x":1}'}},
                        {"id": "call_b", "function": {"name": "fn_2", "arguments": '{"y":2}'}},
                        {"id": "call_c", "function": {"name": "fn_3", "arguments": '{"z":3}'}},
                    ],
                },
                "finish_reason": "tool_calls",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        assert len(output) == 3
        for i, item in enumerate(output):
            assert item["type"] == "function_call"
            assert item["status"] == "completed"
        assert output[0]["name"] == "fn_1"
        assert output[1]["name"] == "fn_2"
        assert output[2]["name"] == "fn_3"
        # id and call_id must match for each
        for item in output:
            assert item["id"] == item["call_id"]

    def test_text_and_multiple_tool_calls_ordering(self):
        """Text + multiple tool calls -> message first, then tool calls in order."""
        openai_result = {
            "choices": [{
                "message": {
                    "content": "I'll use multiple tools.",
                    "tool_calls": [
                        {"id": "call_1", "function": {"name": "search", "arguments": "{}"}},
                        {"id": "call_2", "function": {"name": "fetch", "arguments": "{}"}},
                    ],
                },
                "finish_reason": "tool_calls",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        assert len(output) == 3
        assert output[0]["type"] == "message"
        assert output[0]["content"][0]["text"] == "I'll use multiple tools."
        assert output[1]["type"] == "function_call"
        assert output[1]["name"] == "search"
        assert output[2]["type"] == "function_call"
        assert output[2]["name"] == "fetch"

    def test_missing_usage_in_response(self):
        """Response with missing usage should default to zeros."""
        openai_result = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        }
        resp = responses_compat._build_responses_response(openai_result, "gpt-4o", "resp_nu")
        assert resp["usage"]["input_tokens"] == 0
        assert resp["usage"]["output_tokens"] == 0
        assert resp["usage"]["total_tokens"] == 0

    def test_tool_call_without_id_gets_generated(self):
        """Tool call without id should get a generated call_ id."""
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
        assert output[0]["id"].startswith("call_")
        assert output[0]["id"] == output[0]["call_id"]


# ---------------------------------------------------------------------------
# Edge case: Streaming
# ---------------------------------------------------------------------------


class TestStreamingEdgeCases:
    """Edge cases for the streaming converter."""

    @pytest.mark.asyncio
    async def test_empty_stream_no_content_chunks(self):
        """Empty stream (only DONE) should still produce created + completed events."""
        async def mock_stream():
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_empty2"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]
        assert event_types[0] == "response.created"
        assert event_types[1] == "response.in_progress"
        assert event_types[-1] == "response.completed"
        # No output_item events for empty stream
        assert "response.output_item.added" not in event_types
        assert "response.output_text.delta" not in event_types

    @pytest.mark.asyncio
    async def test_first_chunk_has_content_immediately(self):
        """First chunk with content (no empty delta first) should handle correctly."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"Hello immediately"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_imm"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Should have proper event sequence even with immediate content
        assert event_types[0] == "response.created"
        assert event_types[1] == "response.in_progress"
        assert "response.output_item.added" in event_types
        assert "response.content_part.added" in event_types
        assert "response.output_text.delta" in event_types
        assert "response.output_text.done" in event_types

        # The delta should contain the full first-chunk content
        deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        assert deltas[0]["delta"] == "Hello immediately"

    @pytest.mark.asyncio
    async def test_malformed_json_in_stream_skipped(self):
        """Malformed JSON chunks should be skipped gracefully."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"good"},"index":0}]}\n\n'
            yield 'data: {malformed json\n\n'
            yield 'data: not even close\n\n'
            yield 'data: {"choices":[{"delta":{"content":" text"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_mj"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        # Both good text chunks should make it through
        deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        assert len(deltas) == 2
        assert deltas[0]["delta"] == "good"
        assert deltas[1]["delta"] == " text"

        # Should still complete normally
        event_types = [t for t, _ in parsed]
        assert event_types[-1] == "response.completed"

    @pytest.mark.asyncio
    async def test_bytes_chunks_in_stream(self):
        """Stream chunks as bytes (not str) should be handled."""
        async def mock_stream():
            yield b'data: {"choices":[{"delta":{"content":"from bytes"},"index":0}]}\n\n'
            yield b'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield b'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_bytes"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        assert len(deltas) == 1
        assert deltas[0]["delta"] == "from bytes"
        assert parsed[-1][0] == "response.completed"

    @pytest.mark.asyncio
    async def test_finish_reason_only_chunk(self):
        """Chunk with only finish_reason and no content/tools should be handled."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"text"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_fr"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        completed = [d for t, d in parsed if t == "response.completed"]
        assert len(completed) == 1
        assert completed[0]["response"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_streaming(self):
        """Multiple parallel tool calls should each produce their own output items."""
        async def mock_stream():
            # First tool call arrives
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_a","function":{"name":"search","arguments":""}}]},"index":0}]}\n\n'
            # Second tool call arrives in same chunk batch
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"call_b","function":{"name":"fetch","arguments":""}}]},"index":0}]}\n\n'
            # Args for first tool
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"q\\":\\"test\\"}"}}]},"index":0}]}\n\n'
            # Args for second tool
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"function":{"arguments":"{\\"url\\":\\"http://x\\"}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_mtc"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Two output_item.added (one per tool)
        added = [d for t, d in parsed if t == "response.output_item.added"]
        assert len(added) == 2
        assert added[0]["item"]["name"] == "search"
        assert added[1]["item"]["name"] == "fetch"

        # Two function_call_arguments.done events
        args_done = [d for t, d in parsed if t == "response.function_call_arguments.done"]
        assert len(args_done) == 2
        assert args_done[0]["arguments"] == '{"q":"test"}'
        assert args_done[1]["arguments"] == '{"url":"http://x"}'

        # Two output_item.done events
        item_done = [d for t, d in parsed if t == "response.output_item.done"]
        assert len(item_done) == 2

    @pytest.mark.asyncio
    async def test_text_then_multiple_tool_calls_streaming(self):
        """Text followed by multiple tool calls in streaming."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"Let me help."},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"fn1","arguments":"{}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"call_2","function":{"name":"fn2","arguments":"{}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_tmtc"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Text item should be closed before tool calls
        text_done_idx = event_types.index("response.output_text.done")
        first_tool_added_idx = next(
            i for i, (t, d) in enumerate(parsed)
            if t == "response.output_item.added" and d["item"]["type"] == "function_call"
        )
        assert text_done_idx < first_tool_added_idx

        # 3 output_item.added total (1 text + 2 tools)
        assert event_types.count("response.output_item.added") == 3
        # 3 output_item.done total
        assert event_types.count("response.output_item.done") == 3

    @pytest.mark.asyncio
    async def test_mid_stream_error_without_prior_text(self):
        """Mid-stream error without any prior text should still close properly."""
        async def mock_stream():
            raise RuntimeError("connection refused")
            yield  # make it a generator

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_err_no_text"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        assert event_types[0] == "response.created"
        assert event_types[-1] == "response.completed"
        # Should have error text in delta
        error_deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        assert len(error_deltas) == 1
        assert "connection refused" in error_deltas[0]["delta"]

        # The completed event should have failed status
        completed = [d for t, d in parsed if t == "response.completed"]
        assert completed[0]["response"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_mid_stream_error_with_prior_text(self):
        """Mid-stream error after some text should append error and close properly."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"partial"},"index":0}]}\n\n'
            raise RuntimeError("timeout")

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_err_text"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Should have the original text delta
        deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        assert len(deltas) == 2  # original + error
        assert deltas[0]["delta"] == "partial"
        assert "timeout" in deltas[1]["delta"]

        # Text done should contain both original + error text
        text_done = [d for t, d in parsed if t == "response.output_text.done"]
        assert len(text_done) == 1
        assert "partial" in text_done[0]["text"]
        assert "timeout" in text_done[0]["text"]

        # Completed with failed status
        completed = [d for t, d in parsed if t == "response.completed"]
        assert completed[0]["response"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_empty_tool_calls_array_in_chunk(self):
        """Chunk with empty tool_calls array should not produce any tool events."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"text","tool_calls":[]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_etc"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Should have text events but no tool events
        assert "response.output_text.delta" in event_types
        assert "response.function_call_arguments.delta" not in event_types
        assert "response.function_call_arguments.done" not in event_types

    @pytest.mark.asyncio
    async def test_usage_only_in_separate_chunk(self):
        """Usage arriving in a separate chunk (common pattern) should be captured."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            # Usage in a separate chunk (OpenAI pattern with stream_options)
            yield 'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_usep"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        completed = [d for t, d in parsed if t == "response.completed"]
        usage = completed[0]["response"]["usage"]
        assert usage["input_tokens"] == 10
        assert usage["output_tokens"] == 5


# ---------------------------------------------------------------------------
# Edge case: Integration - empty array input route test
# ---------------------------------------------------------------------------


class TestResponsesEdgeCaseIntegration:
    """Integration tests for edge cases via TestClient."""

    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])

        app = FastAPI()
        app.include_router(responses_compat.responses_compatible_routes)
        self.client = TestClient(app)

    def test_empty_model_string_returns_400(self):
        """Empty string model should be rejected."""
        resp = self.client.post("/v1/responses", json={"model": "", "input": "hi"})
        assert resp.status_code == 400

    def test_empty_array_input_accepted(self, monkeypatch):
        """Empty array input should be accepted and processed."""
        mock_result = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 1, "total_tokens": 1},
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
            "input": [],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "response"

    def test_whitespace_input_accepted(self, monkeypatch):
        """Whitespace-only string input should be accepted."""
        mock_result = {
            "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
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
            "input": "   ",
        })
        assert resp.status_code == 200

    def test_extra_unknown_fields_accepted(self):
        """Extra unknown fields in request body should not cause errors."""
        # Should fail on missing model, not on unknown fields
        resp = self.client.post("/v1/responses", json={
            "input": "hi",
            "store": True,
            "metadata": {"session": "abc"},
            "unknown_field": "value",
        })
        assert resp.status_code == 400
        assert "model" in resp.json()["error"]["message"]

    def test_http_exception_from_mapper(self, monkeypatch):
        """HTTPException from mapper should be caught and returned properly."""
        from fastapi import HTTPException

        async def mock_list_downstream():
            return []

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(
            responses_compat.mapper,
            "resolve_request_config",
            MagicMock(side_effect=HTTPException(status_code=404, detail="Model not found")),
        )

        resp = self.client.post("/v1/responses", json={
            "model": "nonexistent",
            "input": "hi",
        })
        assert resp.status_code == 404
        assert "Model not found" in resp.json()["error"]["message"]

    def test_generic_exception_returns_500(self, monkeypatch):
        """Unexpected exceptions should return 500."""
        async def mock_list_downstream():
            return []

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(
            responses_compat.mapper,
            "resolve_request_config",
            MagicMock(side_effect=RuntimeError("unexpected crash")),
        )

        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hi",
        })
        assert resp.status_code == 500
        assert resp.json()["error"]["type"] == "server_error"


# ---------------------------------------------------------------------------
# Reasoning support: _build_openai_body
# ---------------------------------------------------------------------------


class TestReasoningParamConversion:
    """Test that reasoning parameter is mapped to reasoning_effort."""

    def test_reasoning_effort_mapped(self):
        body = {"model": "o3", "input": "hi", "reasoning": {"effort": "high"}}
        result = responses_compat._build_openai_body(body)
        assert result["reasoning_effort"] == "high"

    def test_reasoning_effort_low(self):
        body = {"model": "o3", "input": "hi", "reasoning": {"effort": "low"}}
        result = responses_compat._build_openai_body(body)
        assert result["reasoning_effort"] == "low"

    def test_reasoning_effort_medium(self):
        body = {"model": "o3", "input": "hi", "reasoning": {"effort": "medium"}}
        result = responses_compat._build_openai_body(body)
        assert result["reasoning_effort"] == "medium"

    def test_no_reasoning_param(self):
        body = {"model": "gpt-4o", "input": "hi"}
        result = responses_compat._build_openai_body(body)
        assert "reasoning_effort" not in result

    def test_reasoning_without_effort(self):
        body = {"model": "o3", "input": "hi", "reasoning": {}}
        result = responses_compat._build_openai_body(body)
        assert "reasoning_effort" not in result

    def test_reasoning_none(self):
        body = {"model": "o3", "input": "hi", "reasoning": None}
        result = responses_compat._build_openai_body(body)
        assert "reasoning_effort" not in result

    def test_reasoning_non_dict(self):
        body = {"model": "o3", "input": "hi", "reasoning": "high"}
        result = responses_compat._build_openai_body(body)
        assert "reasoning_effort" not in result

    def test_reasoning_with_other_params(self):
        body = {
            "model": "o3",
            "input": "hi",
            "reasoning": {"effort": "high"},
            "temperature": 0.5,
            "max_output_tokens": 1000,
        }
        result = responses_compat._build_openai_body(body)
        assert result["reasoning_effort"] == "high"
        assert result["temperature"] == 0.5
        assert result["max_tokens"] == 1000


# ---------------------------------------------------------------------------
# Reasoning support: _build_output_items
# ---------------------------------------------------------------------------


class TestReasoningOutputItems:
    """Test reasoning output items in non-streaming responses."""

    def test_reasoning_content_produces_reasoning_item(self):
        openai_result = {
            "choices": [{
                "message": {
                    "reasoning_content": "Let me think about this...",
                    "content": "The answer is 4.",
                },
                "finish_reason": "stop",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        assert len(output) == 2
        assert output[0]["type"] == "reasoning"
        assert output[0]["id"].startswith("rs_")
        assert len(output[0]["summary"]) == 1
        assert output[0]["summary"][0]["type"] == "summary_text"
        assert output[0]["summary"][0]["text"] == "Let me think about this..."
        assert output[1]["type"] == "message"
        assert output[1]["content"][0]["text"] == "The answer is 4."

    def test_reasoning_field_also_works(self):
        """Some backends use 'reasoning' instead of 'reasoning_content'."""
        openai_result = {
            "choices": [{
                "message": {
                    "reasoning": "Thinking hard...",
                    "content": "42",
                },
                "finish_reason": "stop",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        assert len(output) == 2
        assert output[0]["type"] == "reasoning"
        assert output[0]["summary"][0]["text"] == "Thinking hard..."

    def test_no_reasoning_no_reasoning_item(self):
        openai_result = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
        }
        output = responses_compat._build_output_items(openai_result)
        assert len(output) == 1
        assert output[0]["type"] == "message"

    def test_reasoning_before_message_ordering(self):
        openai_result = {
            "choices": [{
                "message": {
                    "reasoning_content": "Step 1...",
                    "content": "Result",
                },
                "finish_reason": "stop",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        types = [item["type"] for item in output]
        assert types == ["reasoning", "message"]

    def test_reasoning_with_tool_calls(self):
        openai_result = {
            "choices": [{
                "message": {
                    "reasoning_content": "I should search for this",
                    "content": None,
                    "tool_calls": [
                        {"id": "call_1", "function": {"name": "search", "arguments": '{"q":"test"}'}},
                    ],
                },
                "finish_reason": "tool_calls",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        types = [item["type"] for item in output]
        assert types == ["reasoning", "function_call"]

    def test_reasoning_empty_string_ignored(self):
        openai_result = {
            "choices": [{
                "message": {
                    "reasoning_content": "",
                    "content": "hello",
                },
                "finish_reason": "stop",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        assert len(output) == 1
        assert output[0]["type"] == "message"


# ---------------------------------------------------------------------------
# Reasoning support: _build_responses_response with reasoning_tokens
# ---------------------------------------------------------------------------


class TestReasoningTokensInUsage:
    """Test that reasoning tokens from the backend are propagated."""

    def test_reasoning_tokens_from_completion_details(self):
        openai_result = {
            "choices": [{"message": {"content": "4"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 50,
                "total_tokens": 60,
                "completion_tokens_details": {"reasoning_tokens": 40},
            },
        }
        resp = responses_compat._build_responses_response(openai_result, "o3", "resp_rt")
        assert resp["usage"]["output_tokens_details"]["reasoning_tokens"] == 40

    def test_no_completion_details_defaults_to_zero(self):
        openai_result = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }
        resp = responses_compat._build_responses_response(openai_result, "gpt-4o", "resp_nrt")
        assert resp["usage"]["output_tokens_details"]["reasoning_tokens"] == 0


class TestMakeUsageReasoning:
    def test_reasoning_tokens_param(self):
        u = responses_compat._make_usage(reasoning_tokens=25)
        assert u["output_tokens_details"]["reasoning_tokens"] == 25

    def test_reasoning_tokens_default_zero(self):
        u = responses_compat._make_usage()
        assert u["output_tokens_details"]["reasoning_tokens"] == 0


# ---------------------------------------------------------------------------
# Reasoning support: Streaming
# ---------------------------------------------------------------------------


class TestReasoningStreaming:
    """Test reasoning events in streaming responses."""

    @pytest.mark.asyncio
    async def test_reasoning_then_text_stream(self):
        """Reasoning chunks followed by text chunks should produce correct event sequence."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"Let me think"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"reasoning_content":"...carefully."},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"The answer is 4."},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_reason"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Should have reasoning events before text events
        assert "response.output_item.added" in event_types
        assert "response.reasoning_summary_part.added" in event_types
        assert "response.reasoning_summary_text.delta" in event_types
        assert "response.reasoning_summary_text.done" in event_types
        assert "response.reasoning_summary_part.done" in event_types
        assert "response.output_text.delta" in event_types

        # Reasoning events should come before text events
        first_reasoning_delta = next(
            i for i, (t, _) in enumerate(parsed) if t == "response.reasoning_summary_text.delta"
        )
        first_text_delta = next(
            i for i, (t, _) in enumerate(parsed) if t == "response.output_text.delta"
        )
        assert first_reasoning_delta < first_text_delta

    @pytest.mark.asyncio
    async def test_reasoning_item_has_correct_structure(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"Thinking..."},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"4"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_rs"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # Check output_item.added for reasoning
        reasoning_added = [d for t, d in parsed
                          if t == "response.output_item.added" and d["item"]["type"] == "reasoning"]
        assert len(reasoning_added) == 1
        assert reasoning_added[0]["item"]["id"].startswith("rs_")
        assert reasoning_added[0]["item"]["summary"] == []

        # Check reasoning_summary_part.added
        part_added = [d for t, d in parsed if t == "response.reasoning_summary_part.added"]
        assert len(part_added) == 1
        assert part_added[0]["summary_index"] == 0
        assert part_added[0]["part"]["type"] == "summary_text"
        assert part_added[0]["part"]["text"] == ""

    @pytest.mark.asyncio
    async def test_reasoning_deltas_accumulated(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"A"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"reasoning_content":"B"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"reasoning_content":"C"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"Result"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_racc"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # 3 reasoning deltas
        reasoning_deltas = [d for t, d in parsed if t == "response.reasoning_summary_text.delta"]
        assert len(reasoning_deltas) == 3
        assert reasoning_deltas[0]["delta"] == "A"
        assert reasoning_deltas[1]["delta"] == "B"
        assert reasoning_deltas[2]["delta"] == "C"

        # Done event should have accumulated text
        reasoning_done = [d for t, d in parsed if t == "response.reasoning_summary_text.done"]
        assert len(reasoning_done) == 1
        assert reasoning_done[0]["text"] == "ABC"

        # Part done should also have accumulated text
        part_done = [d for t, d in parsed if t == "response.reasoning_summary_part.done"]
        assert len(part_done) == 1
        assert part_done[0]["part"]["text"] == "ABC"

    @pytest.mark.asyncio
    async def test_reasoning_output_item_done(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"Think"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"Done"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_roid"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # output_item.done for reasoning should come before text item opens
        reasoning_item_done = [
            d for t, d in parsed
            if t == "response.output_item.done" and d["item"]["type"] == "reasoning"
        ]
        assert len(reasoning_item_done) == 1
        item = reasoning_item_done[0]["item"]
        assert item["id"].startswith("rs_")
        assert len(item["summary"]) == 1
        assert item["summary"][0]["type"] == "summary_text"
        assert item["summary"][0]["text"] == "Think"

    @pytest.mark.asyncio
    async def test_reasoning_only_no_text(self):
        """Stream with only reasoning content and no text should still close properly."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"Just thinking..."},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_ro"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        assert "response.reasoning_summary_text.delta" in event_types
        assert "response.reasoning_summary_text.done" in event_types
        assert "response.reasoning_summary_part.done" in event_types
        assert event_types[-1] == "response.completed"

        # No text events
        assert "response.output_text.delta" not in event_types

    @pytest.mark.asyncio
    async def test_reasoning_with_tool_calls_stream(self):
        """Reasoning followed by tool calls in streaming."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"I need to search"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"search","arguments":"{\\"q\\":\\"test\\"}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_rtc"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Reasoning should be closed before tool call opens
        reasoning_done_idx = event_types.index("response.reasoning_summary_text.done")
        tool_added_idx = next(
            i for i, (t, d) in enumerate(parsed)
            if t == "response.output_item.added" and d["item"]["type"] == "function_call"
        )
        assert reasoning_done_idx < tool_added_idx

    @pytest.mark.asyncio
    async def test_reasoning_uses_reasoning_field(self):
        """Some backends use 'reasoning' instead of 'reasoning_content'."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning":"Alt field"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"Done"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_altf"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        reasoning_deltas = [d for t, d in parsed if t == "response.reasoning_summary_text.delta"]
        assert len(reasoning_deltas) == 1
        assert reasoning_deltas[0]["delta"] == "Alt field"

    @pytest.mark.asyncio
    async def test_reasoning_sequence_numbers_monotonic(self):
        """All events including reasoning should have monotonically increasing sequence numbers."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"Think"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"Answer"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_seqr"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        seq_nums = [d.get("sequence_number") for _, d in parsed]
        for i in range(1, len(seq_nums)):
            assert seq_nums[i] > seq_nums[i - 1], \
                f"sequence_number not monotonically increasing: {seq_nums}"

    @pytest.mark.asyncio
    async def test_reasoning_output_indices(self):
        """Reasoning and text items should have different output indices."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"Think"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"Answer"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_oidx"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # Find output indices for reasoning and text items
        reasoning_added = [d for t, d in parsed
                          if t == "response.output_item.added" and d["item"]["type"] == "reasoning"]
        text_added = [d for t, d in parsed
                     if t == "response.output_item.added" and d["item"]["type"] == "message"]

        assert len(reasoning_added) == 1
        assert len(text_added) == 1
        assert reasoning_added[0]["output_index"] < text_added[0]["output_index"]

    @pytest.mark.asyncio
    async def test_mid_stream_error_after_reasoning(self):
        """Error after reasoning should close reasoning and emit error text."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"Thinking..."},"index":0}]}\n\n'
            raise RuntimeError("connection lost")

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_rerr"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Reasoning should be closed
        assert "response.reasoning_summary_text.done" in event_types
        assert "response.reasoning_summary_part.done" in event_types

        # Error text should appear
        error_deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        assert len(error_deltas) == 1
        assert "connection lost" in error_deltas[0]["delta"]

        # Completed with failed status
        completed = [d for t, d in parsed if t == "response.completed"]
        assert completed[0]["response"]["status"] == "failed"


# ---------------------------------------------------------------------------
# Reasoning support: Integration tests
# ---------------------------------------------------------------------------


class TestReasoningIntegration:
    """Integration tests for reasoning support via TestClient."""

    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])

        app = FastAPI()
        app.include_router(responses_compat.responses_compatible_routes)
        self.client = TestClient(app)

    def test_reasoning_param_passed_through(self, monkeypatch):
        """reasoning.effort should be mapped to reasoning_effort in the downstream request."""
        captured_body = {}

        async def mock_list_downstream():
            return []

        def mock_resolve(body):
            captured_body.update(body)
            return {}

        mock_result = {
            "choices": [{"message": {"content": "4"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
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
        monkeypatch.setattr(responses_compat.mapper, "resolve_request_config", mock_resolve)
        monkeypatch.setattr(responses_compat.mapper, "is_direct_task", lambda proxy: False)
        monkeypatch.setattr(responses_compat.llm_mod, "LLM", lambda **kw: mock_llm)

        resp = self.client.post("/v1/responses", json={
            "model": "o3",
            "input": "What is 2+2?",
            "reasoning": {"effort": "high"},
        })

        assert resp.status_code == 200
        assert captured_body.get("reasoning_effort") == "high"

    def test_non_streaming_reasoning_response(self, monkeypatch):
        """Non-streaming response with reasoning_content should include reasoning output item."""
        mock_result = {
            "choices": [{
                "message": {
                    "reasoning_content": "Let me think step by step...",
                    "content": "The answer is 4.",
                },
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 50,
                "total_tokens": 60,
                "completion_tokens_details": {"reasoning_tokens": 40},
            },
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
            "model": "o3",
            "input": "What is 2+2?",
            "reasoning": {"effort": "high"},
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "response"
        assert len(body["output"]) == 2
        assert body["output"][0]["type"] == "reasoning"
        assert body["output"][0]["summary"][0]["text"] == "Let me think step by step..."
        assert body["output"][1]["type"] == "message"
        assert body["output"][1]["content"][0]["text"] == "The answer is 4."
        assert body["usage"]["output_tokens_details"]["reasoning_tokens"] == 40

    def test_streaming_reasoning_response(self, monkeypatch):
        """Streaming response with reasoning chunks should emit reasoning events."""
        async def mock_list_downstream():
            return []

        mock_llm = MagicMock()
        mock_llm.workflow = None
        mock_llm.boost_params = {}

        async def mock_serve():
            async def gen():
                yield 'data: {"choices":[{"delta":{"reasoning_content":"Thinking..."},"index":0}]}\n\n'
                yield 'data: {"choices":[{"delta":{"content":"4"},"index":0}]}\n\n'
                yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}\n\n'
                yield 'data: [DONE]\n\n'
            return gen()

        mock_llm.serve = mock_serve

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(responses_compat.mapper, "resolve_request_config", lambda body: {})
        monkeypatch.setattr(responses_compat.mapper, "is_direct_task", lambda proxy: False)
        monkeypatch.setattr(responses_compat.llm_mod, "LLM", lambda **kw: mock_llm)

        resp = self.client.post("/v1/responses", json={
            "model": "o3",
            "input": "What is 2+2?",
            "reasoning": {"effort": "high"},
            "stream": True,
        })

        assert resp.status_code == 200
        text = resp.text
        assert "response.reasoning_summary_part.added" in text
        assert "response.reasoning_summary_text.delta" in text
        assert "response.reasoning_summary_text.done" in text
        assert "response.reasoning_summary_part.done" in text
        assert "response.output_text.delta" in text
        assert "response.completed" in text
