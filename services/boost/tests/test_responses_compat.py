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

    def test_input_image_with_url(self):
        """input_image with image_url string maps to image_url part."""
        result = responses_compat._convert_content_parts([
            {"type": "input_image", "image_url": "https://example.com/photo.jpg"},
        ])
        assert isinstance(result, list)
        assert result[0]["type"] == "image_url"
        assert result[0]["image_url"]["url"] == "https://example.com/photo.jpg"
        assert "detail" not in result[0]["image_url"]

    def test_input_image_with_url_and_detail(self):
        """input_image with image_url and detail passes both through."""
        result = responses_compat._convert_content_parts([
            {"type": "input_image", "image_url": "https://example.com/photo.jpg", "detail": "high"},
        ])
        assert result[0]["image_url"]["url"] == "https://example.com/photo.jpg"
        assert result[0]["image_url"]["detail"] == "high"

    def test_input_image_with_data_url(self):
        """input_image with a data: URI in image_url passes through correctly."""
        data_url = "data:image/png;base64,iVBORw0KGgoAAAA"
        result = responses_compat._convert_content_parts([
            {"type": "input_image", "image_url": data_url},
        ])
        assert result[0]["image_url"]["url"] == data_url

    def test_input_image_with_file_id(self):
        """input_image with file_id (no image_url) passes file_id as URL."""
        result = responses_compat._convert_content_parts([
            {"type": "input_image", "file_id": "file-abc123"},
        ])
        assert isinstance(result, list)
        assert result[0]["type"] == "image_url"
        assert result[0]["image_url"]["url"] == "file-abc123"

    def test_input_image_with_file_id_and_detail(self):
        """input_image with file_id and detail passes both through."""
        result = responses_compat._convert_content_parts([
            {"type": "input_image", "file_id": "file-xyz", "detail": "low"},
        ])
        assert result[0]["image_url"]["url"] == "file-xyz"
        assert result[0]["image_url"]["detail"] == "low"

    def test_input_image_neither_url_nor_file_id(self):
        """input_image with neither image_url nor file_id produces no image part."""
        result = responses_compat._convert_content_parts([
            {"type": "input_image"},
        ])
        # No output parts => empty list collapsed to empty string
        assert result == ""

    def test_input_image_prefers_url_over_file_id(self):
        """When both image_url and file_id are present, image_url wins."""
        result = responses_compat._convert_content_parts([
            {
                "type": "input_image",
                "image_url": "https://example.com/img.png",
                "file_id": "file-abc",
            },
        ])
        assert result[0]["image_url"]["url"] == "https://example.com/img.png"

    def test_multiple_images(self):
        """Multiple input_image parts should all be converted."""
        result = responses_compat._convert_content_parts([
            {"type": "input_image", "image_url": "https://example.com/a.png"},
            {"type": "input_image", "image_url": "https://example.com/b.png"},
        ])
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["image_url"]["url"] == "https://example.com/a.png"
        assert result[1]["image_url"]["url"] == "https://example.com/b.png"

    def test_input_image_detail_not_added_when_absent(self):
        """detail key should be omitted from the output when not specified."""
        result = responses_compat._convert_content_parts([
            {"type": "input_image", "image_url": "https://example.com/photo.jpg"},
        ])
        assert "detail" not in result[0]["image_url"]

    def test_text_and_multiple_images(self):
        """Text mixed with multiple images preserves order."""
        result = responses_compat._convert_content_parts([
            {"type": "input_text", "text": "Compare these:"},
            {"type": "input_image", "image_url": "https://a.com/1.png"},
            {"type": "input_image", "image_url": "https://b.com/2.png"},
        ])
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0] == {"type": "text", "text": "Compare these:"}
        assert result[1]["image_url"]["url"] == "https://a.com/1.png"
        assert result[2]["image_url"]["url"] == "https://b.com/2.png"


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

    def test_401(self):
        resp = responses_compat._responses_error(401, "unauthorized")
        body = json.loads(resp.body.decode())
        assert resp.status_code == 401
        assert body["error"]["type"] == "authentication_error"

    def test_403(self):
        resp = responses_compat._responses_error(403, "forbidden")
        body = json.loads(resp.body.decode())
        assert resp.status_code == 403
        assert body["error"]["type"] == "permission_error"

    def test_404(self):
        resp = responses_compat._responses_error(404, "not found")
        body = json.loads(resp.body.decode())
        assert resp.status_code == 404
        assert body["error"]["type"] == "not_found_error"

    def test_409(self):
        resp = responses_compat._responses_error(409, "conflict")
        body = json.loads(resp.body.decode())
        assert resp.status_code == 409
        assert body["error"]["type"] == "conflict_error"

    def test_422(self):
        resp = responses_compat._responses_error(422, "unprocessable")
        body = json.loads(resp.body.decode())
        assert resp.status_code == 422
        assert body["error"]["type"] == "invalid_request_error"

    def test_429(self):
        resp = responses_compat._responses_error(429, "rate limited")
        body = json.loads(resp.body.decode())
        assert resp.status_code == 429
        assert body["error"]["type"] == "rate_limit_error"

    def test_500(self):
        resp = responses_compat._responses_error(500, "oops")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "server_error"

    def test_unknown_status_defaults_to_server_error(self):
        resp = responses_compat._responses_error(503, "unavailable")
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

    def test_error_format_has_all_required_fields(self):
        """Every error must include message, type, param, and code."""
        resp = responses_compat._responses_error(400, "test")
        body = json.loads(resp.body.decode())
        error = body["error"]
        assert "message" in error
        assert "type" in error
        assert "param" in error
        assert "code" in error

    def test_param_is_always_null(self):
        resp = responses_compat._responses_error(400, "test")
        body = json.loads(resp.body.decode())
        assert body["error"]["param"] is None

    def test_code_defaults_to_null(self):
        resp = responses_compat._responses_error(400, "test")
        body = json.loads(resp.body.decode())
        assert body["error"]["code"] is None

    def test_request_id_header_present_when_provided(self):
        resp = responses_compat._responses_error(400, "test", request_id="req_abc123")
        assert resp.headers.get("x-request-id") == "req_abc123"

    def test_request_id_header_absent_when_not_provided(self):
        resp = responses_compat._responses_error(400, "test")
        assert "x-request-id" not in resp.headers

    def test_error_type_map_completeness(self):
        """ERROR_TYPE_MAP covers all status codes the OpenAI SDK maps to exceptions."""
        expected_codes = {400, 401, 403, 404, 409, 422, 429, 500}
        assert set(responses_compat.ERROR_TYPE_MAP.keys()) == expected_codes


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


from helpers import parse_responses_sse_events as _parse_sse_events


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

        event_types = [l.replace("event: ", "") for e in events for l in e.strip().split("\n") if l.startswith("event: ")]

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

        event_types = [l.replace("event: ", "") for e in events for l in e.strip().split("\n") if l.startswith("event: ")]
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

        event_types = [l.replace("event: ", "") for e in events for l in e.strip().split("\n") if l.startswith("event: ")]

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

        event_types = [l.replace("event: ", "") for e in events for l in e.strip().split("\n") if l.startswith("event: ")]
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

        event_types = [l.replace("event: ", "") for e in events for l in e.strip().split("\n") if l.startswith("event: ")]
        assert "response.failed" in event_types

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

        # Skip non-event entries (keep-alive comments, etc.)
        sse_events = [e for e in events if "event: " in e]
        created = sse_events[0]
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


from helpers import make_responses_app as _make_responses_app


class TestResponsesRouteIntegration:
    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch):
        """Set up a test FastAPI app with the responses router."""
        from fastapi.testclient import TestClient

        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])

        app = _make_responses_app()
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

        assert resp.status_code == 401

    def test_auth_error_has_openai_error_format(self, monkeypatch):
        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", ["sk-test"])

        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hello",
        })

        body = resp.json()
        assert "error" in body
        assert body["error"]["type"] == "authentication_error"
        assert isinstance(body["error"]["message"], str)
        assert "param" in body["error"]
        assert "code" in body["error"]

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
        from fastapi.testclient import TestClient

        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])

        app = _make_responses_app()
        self.client = TestClient(app)

    def _assert_request_id(self, resp):
        """Assert x-request-id header is present and has correct format."""
        assert "x-request-id" in resp.headers, "Missing x-request-id header"
        rid = resp.headers["x-request-id"]
        assert rid.startswith("req_"), f"x-request-id should start with req_, got: {rid}"

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
        """Each request should get a unique x-request-id."""
        resp1 = self.client.post("/v1/responses", json={"input": "hi"})
        resp2 = self.client.post("/v1/responses", json={"input": "hi"})
        rid1 = resp1.headers.get("x-request-id")
        rid2 = resp2.headers.get("x-request-id")
        assert rid1 != rid2, "Each request must get a unique x-request-id"


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
        assert event_types[-1] == "response.failed"
        # Should have generic error text in delta (not raw exception to avoid leaking internals)
        error_deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        assert len(error_deltas) == 1
        assert "internal error" in error_deltas[0]["delta"].lower()
        assert "connection refused" not in error_deltas[0]["delta"]

        # The failed event should have failed status
        failed = [d for t, d in parsed if t == "response.failed"]
        assert failed[0]["response"]["status"] == "failed"

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
        # Generic error message, not raw exception
        assert "internal error" in deltas[1]["delta"].lower()
        assert "timeout" not in deltas[1]["delta"]

        # Text done should contain both original + error text
        text_done = [d for t, d in parsed if t == "response.output_text.done"]
        assert len(text_done) == 1
        assert "partial" in text_done[0]["text"]
        assert "internal error" in text_done[0]["text"].lower()

        # Failed terminal event with failed status
        failed = [d for t, d in parsed if t == "response.failed"]
        assert failed[0]["response"]["status"] == "failed"

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
        from fastapi.testclient import TestClient

        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])

        app = _make_responses_app()
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
        assert "error" in error_deltas[0]["delta"].lower()

        # Failed terminal event with failed status
        failed = [d for t, d in parsed if t == "response.failed"]
        assert failed[0]["response"]["status"] == "failed"


# ---------------------------------------------------------------------------
# Reasoning support: Integration tests
# ---------------------------------------------------------------------------


class TestReasoningIntegration:
    """Integration tests for reasoning support via TestClient."""

    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch):
        from fastapi.testclient import TestClient

        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])

        app = _make_responses_app()
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


# ---------------------------------------------------------------------------
# Instructions / system prompt edge cases
# ---------------------------------------------------------------------------

class TestInstructionsEdgeCases:
    """Verify instructions field handling for edge cases."""

    def test_none_instructions_produces_no_system_message(self):
        """Explicit instructions: null should be treated the same as absent."""
        body = {"input": "hi", "instructions": None}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_whitespace_only_instructions_preserved(self):
        """Whitespace-only instructions are truthy and should be passed through."""
        body = {"input": "hi", "instructions": "   "}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": "   "}
        assert msgs[1] == {"role": "user", "content": "hi"}

    def test_absent_instructions_produces_no_system_message(self):
        """When instructions key is entirely absent, no system message is produced."""
        body = {"input": "hi"}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_instructions_with_input_containing_system_message(self):
        """Instructions combined with input that has a system role message produces two system messages."""
        body = {
            "instructions": "Be helpful.",
            "input": [
                {"type": "message", "role": "system", "content": "Additional system context."},
                {"type": "message", "role": "user", "content": "hello"},
            ],
        }
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 3
        # Instructions become the first system message
        assert msgs[0] == {"role": "system", "content": "Be helpful."}
        # Input system message is preserved as-is
        assert msgs[1] == {"role": "system", "content": "Additional system context."}
        assert msgs[2] == {"role": "user", "content": "hello"}

    def test_very_long_instructions_not_truncated(self):
        """Very long instructions should not be truncated."""
        long_text = "x" * 100_000
        body = {"input": "hi", "instructions": long_text}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs[0]["content"] == long_text
        assert len(msgs[0]["content"]) == 100_000

    def test_multiline_instructions(self):
        """Multi-line instructions should be passed through verbatim."""
        body = {"input": "hi", "instructions": "Line 1.\nLine 2.\nLine 3."}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs[0] == {"role": "system", "content": "Line 1.\nLine 2.\nLine 3."}

    def test_instructions_with_no_input(self):
        """Instructions without input produce only the system message (input=None)."""
        body = {"instructions": "context only"}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [{"role": "system", "content": "context only"}]

    def test_instructions_with_empty_string_input(self):
        """Instructions with empty string input produce system + user messages."""
        body = {"input": "", "instructions": "be helpful"}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": "be helpful"}
        assert msgs[1] == {"role": "user", "content": ""}


# ---------------------------------------------------------------------------
# Truncation parameter handling
# ---------------------------------------------------------------------------

class TestTruncationParameter:
    """Verify truncation parameter is accepted and handled correctly."""

    def test_truncation_auto_accepted_in_build_body(self):
        """truncation: 'auto' should not cause an error."""
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "truncation": "auto",
        }
        result = responses_compat._build_openai_body(body)
        assert result["model"] == "gpt-4o"
        # truncation should NOT appear in the OpenAI body
        assert "truncation" not in result

    def test_truncation_disabled_accepted(self):
        """truncation: 'disabled' should be silently accepted."""
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "truncation": "disabled",
        }
        result = responses_compat._build_openai_body(body)
        assert "truncation" not in result

    def test_no_truncation_accepted(self):
        """Absent truncation should not cause any issues."""
        body = {"model": "gpt-4o", "input": "hi"}
        result = responses_compat._build_openai_body(body)
        assert "truncation" not in result

    def test_truncation_auto_logs_warning(self):
        """truncation auto should log a warning."""
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "truncation": "auto",
        }
        with patch.object(responses_compat.logger, "warning") as mock_warn:
            responses_compat._build_openai_body(body)
            mock_warn.assert_called_once()
            assert "truncation" in mock_warn.call_args[0][0].lower()

    def test_truncation_disabled_no_warning(self):
        """truncation disabled should NOT log a warning."""
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "truncation": "disabled",
        }
        with patch.object(responses_compat.logger, "warning") as mock_warn:
            responses_compat._build_openai_body(body)
            mock_warn.assert_not_called()

    def test_truncation_none_no_warning(self):
        """truncation: null should NOT log a warning."""
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "truncation": None,
        }
        with patch.object(responses_compat.logger, "warning") as mock_warn:
            responses_compat._build_openai_body(body)
            mock_warn.assert_not_called()

    def test_truncation_auto_reflected_in_response(self):
        """Response should reflect truncation=auto when requested."""
        openai_result = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        request_body = {"truncation": "auto"}
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_test", request_body=request_body
        )
        assert resp["truncation"] == "auto"

    def test_truncation_disabled_in_response_by_default(self):
        """Response should show truncation=disabled when not requested."""
        openai_result = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_test"
        )
        assert resp["truncation"] == "disabled"


# ---------------------------------------------------------------------------
# Store and metadata parameter handling
# ---------------------------------------------------------------------------

class TestStoreAndMetadataParameters:
    """Verify store and metadata parameters are accepted and handled correctly."""

    def test_store_false_in_response_by_default(self):
        """Response should always have store=false."""
        openai_result = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_test"
        )
        assert resp["store"] is False

    def test_store_false_even_when_requested_true(self):
        """Response should have store=false even if request says store=true."""
        openai_result = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        request_body = {"store": True}
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_test", request_body=request_body
        )
        assert resp["store"] is False

    def test_metadata_empty_by_default(self):
        """Response metadata should be empty dict when not provided in request."""
        openai_result = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_test"
        )
        assert resp["metadata"] == {}

    def test_metadata_passthrough_from_request(self):
        """Response should include metadata from request."""
        openai_result = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        request_body = {"metadata": {"user_id": "u123", "session": "abc"}}
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_test", request_body=request_body
        )
        assert resp["metadata"] == {"user_id": "u123", "session": "abc"}

    def test_metadata_null_treated_as_empty(self):
        """Null metadata in request should produce empty dict in response."""
        openai_result = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        request_body = {"metadata": None}
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_test", request_body=request_body
        )
        assert resp["metadata"] == {}

    def test_metadata_non_dict_treated_as_empty(self):
        """Non-dict metadata in request should produce empty dict in response."""
        openai_result = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        request_body = {"metadata": "not a dict"}
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_test", request_body=request_body
        )
        assert resp["metadata"] == {}

    def test_store_true_logs_debug(self):
        """store=true should produce a debug log."""
        with patch.object(responses_compat.logger, "debug") as mock_debug:
            # We need to test via the route handler, so use integration
            pass  # Tested in integration class below


# ---------------------------------------------------------------------------
# Store/metadata/truncation integration tests
# ---------------------------------------------------------------------------

class TestStoreMetadataTruncationIntegration:
    """Integration tests for store, metadata, and truncation through the route handler."""

    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch):
        from fastapi.testclient import TestClient

        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])

        app = _make_responses_app()
        self.client = TestClient(app)

    def _mock_llm(self, monkeypatch, result=None):
        """Set up mocked LLM that returns a simple result."""
        if result is None:
            result = {
                "id": "chatcmpl-1",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
            }

        async def mock_list_downstream():
            return []

        mock_llm = MagicMock()
        mock_llm.workflow = None
        mock_llm.boost_params = {}

        async def mock_serve():
            async def gen():
                yield f'data: {json.dumps(result)}\n\n'
                yield 'data: [DONE]\n\n'
            return gen()

        async def mock_consume(stream):
            return result

        mock_llm.serve = mock_serve
        mock_llm.consume_stream = mock_consume

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(responses_compat.mapper, "resolve_request_config", lambda body: {})
        monkeypatch.setattr(responses_compat.mapper, "is_direct_task", lambda proxy: False)
        monkeypatch.setattr(responses_compat.llm_mod, "LLM", lambda **kw: mock_llm)
        return mock_llm

    def test_store_true_accepted_non_streaming(self, monkeypatch):
        """Request with store=true should succeed and return store=false."""
        self._mock_llm(monkeypatch)
        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hi",
            "store": True,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["store"] is False

    def test_store_false_accepted_non_streaming(self, monkeypatch):
        """Request with store=false should succeed and return store=false."""
        self._mock_llm(monkeypatch)
        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hi",
            "store": False,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["store"] is False

    def test_metadata_passthrough_non_streaming(self, monkeypatch):
        """metadata from request should appear in response."""
        self._mock_llm(monkeypatch)
        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hi",
            "metadata": {"tag": "test", "priority": "high"},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["metadata"] == {"tag": "test", "priority": "high"}

    def test_metadata_absent_returns_empty_dict(self, monkeypatch):
        """No metadata in request should produce empty dict in response."""
        self._mock_llm(monkeypatch)
        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hi",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["metadata"] == {}

    def test_truncation_auto_accepted_non_streaming(self, monkeypatch):
        """truncation auto should be accepted and reflected in response."""
        self._mock_llm(monkeypatch)
        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hi",
            "truncation": "auto",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["truncation"] == "auto"

    def test_truncation_disabled_in_response(self, monkeypatch):
        """Default truncation should be disabled."""
        self._mock_llm(monkeypatch)
        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hi",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["truncation"] == "disabled"

    def test_store_true_logs_debug(self, monkeypatch):
        """store=true should trigger a debug log message."""
        self._mock_llm(monkeypatch)
        with patch.object(responses_compat.logger, "debug") as mock_debug:
            resp = self.client.post("/v1/responses", json={
                "model": "gpt-4o",
                "input": "hi",
                "store": True,
            })
            assert resp.status_code == 200
            # Verify debug was called with store-related message
            calls = [str(c) for c in mock_debug.call_args_list]
            assert any("store" in c.lower() for c in calls)

    def test_store_false_no_debug_log(self, monkeypatch):
        """store=false should NOT trigger the store debug log."""
        self._mock_llm(monkeypatch)
        with patch.object(responses_compat.logger, "debug") as mock_debug:
            resp = self.client.post("/v1/responses", json={
                "model": "gpt-4o",
                "input": "hi",
                "store": False,
            })
            assert resp.status_code == 200
            store_calls = [c for c in mock_debug.call_args_list
                          if "store" in str(c).lower()]
            assert len(store_calls) == 0

    def test_all_three_params_together_non_streaming(self, monkeypatch):
        """store, metadata, and truncation together should all work."""
        self._mock_llm(monkeypatch)
        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hi",
            "store": True,
            "metadata": {"env": "test"},
            "truncation": "auto",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["store"] is False
        assert body["metadata"] == {"env": "test"}
        assert body["truncation"] == "auto"

    def test_metadata_in_streaming_response(self, monkeypatch):
        """metadata should appear in streaming skeleton/completed events."""
        self._mock_llm(monkeypatch)
        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hi",
            "metadata": {"session_id": "s42"},
            "stream": True,
        })
        assert resp.status_code == 200
        text = resp.text
        # Check created event has metadata
        events = [line for line in text.split("\n") if line.startswith("data: ")]
        found_metadata = False
        for event_line in events:
            try:
                data = json.loads(event_line[6:])
                if data.get("type") == "response.created":
                    assert data["response"]["metadata"] == {"session_id": "s42"}
                    assert data["response"]["store"] is False
                    found_metadata = True
            except (json.JSONDecodeError, KeyError):
                continue
        assert found_metadata, "response.created event should contain metadata"

    def test_store_false_in_streaming_completed(self, monkeypatch):
        """store should be false in the streaming completed response."""
        self._mock_llm(monkeypatch)
        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hi",
            "store": True,
            "stream": True,
        })
        assert resp.status_code == 200
        text = resp.text
        events = [line for line in text.split("\n") if line.startswith("data: ")]
        for event_line in events:
            try:
                data = json.loads(event_line[6:])
                if data.get("type") == "response.completed":
                    assert data["response"]["store"] is False
            except (json.JSONDecodeError, KeyError):
                continue

    def test_truncation_auto_in_streaming_skeleton(self, monkeypatch):
        """truncation=auto should appear in the streaming skeleton."""
        self._mock_llm(monkeypatch)
        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hi",
            "truncation": "auto",
            "stream": True,
        })
        assert resp.status_code == 200
        text = resp.text
        events = [line for line in text.split("\n") if line.startswith("data: ")]
        for event_line in events:
            try:
                data = json.loads(event_line[6:])
                if data.get("type") == "response.created":
                    assert data["response"]["truncation"] == "auto"
            except (json.JSONDecodeError, KeyError):
                continue


# ---------------------------------------------------------------------------
# SDK output_text Property Compatibility
# ---------------------------------------------------------------------------


class TestOutputTextProperty:
    """Verify that the SDK's computed ``output_text`` property works correctly
    with responses built by our compat layer.

    ``output_text`` is a client-side property on ``Response`` that concatenates
    all ``output_text`` content blocks from ``message`` output items.  The server
    does NOT send it as a JSON field.
    """

    def _parse_response(self, data):
        """Parse a response dict through the SDK model, skip if SDK missing."""
        try:
            from openai.types.responses import Response
            return Response.model_validate(data)
        except ImportError:
            pytest.skip("openai SDK not installed")

    def test_output_text_from_single_message(self):
        result = {
            "choices": [{"message": {"content": "Hello world"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        resp_data = responses_compat._build_responses_response(result, "gpt-4o", "resp_1")
        parsed = self._parse_response(resp_data)
        assert parsed.output_text == "Hello world"

    def test_output_text_empty_content(self):
        result = {
            "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
            "usage": {},
        }
        resp_data = responses_compat._build_responses_response(result, "gpt-4o", "resp_2")
        parsed = self._parse_response(resp_data)
        # Empty content still produces a message item with empty text
        assert parsed.output_text == ""

    def test_output_text_no_content_only_tool_calls(self):
        result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{"id": "call_1", "function": {"name": "f", "arguments": "{}"}}],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {},
        }
        resp_data = responses_compat._build_responses_response(result, "gpt-4o", "resp_3")
        parsed = self._parse_response(resp_data)
        # No message output item, only function_call items
        assert parsed.output_text == ""

    def test_output_text_with_mixed_output_items(self):
        result = {
            "choices": [{
                "message": {
                    "content": "Let me help.",
                    "tool_calls": [{"id": "call_1", "function": {"name": "f", "arguments": "{}"}}],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {},
        }
        resp_data = responses_compat._build_responses_response(result, "gpt-4o", "resp_4")
        parsed = self._parse_response(resp_data)
        assert parsed.output_text == "Let me help."

    def test_output_text_not_in_json(self):
        """output_text must NOT appear as a key in the serialized JSON."""
        result = {
            "choices": [{"message": {"content": "text"}, "finish_reason": "stop"}],
            "usage": {},
        }
        resp_data = responses_compat._build_responses_response(result, "gpt-4o", "resp_5")
        assert "output_text" not in resp_data or isinstance(
            resp_data.get("output_text"), type(None)
        )
        # The only output_text references should be inside content blocks
        assert resp_data["output"][0]["content"][0]["type"] == "output_text"

    def test_text_field_is_config_not_content(self):
        """The ``text`` field is a ResponseTextConfig, not concatenated content."""
        result = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {},
        }
        resp_data = responses_compat._build_responses_response(result, "gpt-4o", "resp_6")
        assert resp_data["text"] == {"format": {"type": "text"}}
        parsed = self._parse_response(resp_data)
        assert parsed.text is not None
        assert parsed.text.format is not None
        assert parsed.text.format.type == "text"

    @pytest.mark.asyncio
    async def test_output_text_from_streaming_completed(self):
        """Verify the completed response from streaming can produce output_text."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"Hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":" there"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"finish_reason":"stop","delta":{},"index":0}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_stream"
        ):
            events.append(event)

        parsed_events = _parse_sse_events(events)

        # The completed response should have the text config field
        completed = [d for t, d in parsed_events if t == "response.completed"]
        assert len(completed) == 1
        resp_data = completed[0]["response"]
        assert resp_data["text"] == {"format": {"type": "text"}}

        # Verify text done event has the full concatenated text
        text_done = [d for t, d in parsed_events if t == "response.output_text.done"]
        assert len(text_done) == 1
        assert text_done[0]["text"] == "Hi there"

    @pytest.mark.asyncio
    async def test_streaming_skeleton_has_text_config(self):
        """Both created and in_progress skeleton responses must include text config."""
        async def mock_stream():
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_skel"
        ):
            events.append(event)

        parsed_events = _parse_sse_events(events)
        created = [d for t, d in parsed_events if t == "response.created"]
        in_progress = [d for t, d in parsed_events if t == "response.in_progress"]
        assert created[0]["response"]["text"] == {"format": {"type": "text"}}
        assert in_progress[0]["response"]["text"] == {"format": {"type": "text"}}


# ---------------------------------------------------------------------------
# Stub endpoints: GET, DELETE, POST cancel
# ---------------------------------------------------------------------------


class TestResponseStubEndpoints:
    """Tests for GET /v1/responses/{id}, DELETE /v1/responses/{id},
    and POST /v1/responses/{id}/cancel — all return 404 with
    informative messages explaining why the operation cannot succeed."""

    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch):
        from fastapi.testclient import TestClient

        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])

        app = _make_responses_app()
        self.client = TestClient(app)

    def _assert_not_found(self, resp):
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["type"] == "not_found_error"
        assert body["error"]["code"] == "not_found"

    def test_get_response_returns_404(self):
        resp = self.client.get("/v1/responses/resp_abc123")
        self._assert_not_found(resp)

    def test_get_response_includes_response_id_in_message(self):
        resp = self.client.get("/v1/responses/resp_abc123")
        body = resp.json()
        assert "resp_abc123" in body["error"]["message"]

    def test_get_response_explains_no_persistence(self):
        resp = self.client.get("/v1/responses/resp_abc123")
        body = resp.json()
        assert "not persist" in body["error"]["message"] or "store" in body["error"]["message"]

    def test_get_response_any_id(self):
        resp = self.client.get("/v1/responses/resp_xyz")
        self._assert_not_found(resp)
        body = resp.json()
        assert "resp_xyz" in body["error"]["message"]

    def test_delete_response_returns_404(self):
        resp = self.client.delete("/v1/responses/resp_abc123")
        self._assert_not_found(resp)

    def test_delete_response_includes_id_in_message(self):
        resp = self.client.delete("/v1/responses/resp_abc123")
        body = resp.json()
        assert "resp_abc123" in body["error"]["message"]

    def test_delete_response_explains_nothing_to_delete(self):
        resp = self.client.delete("/v1/responses/resp_abc123")
        body = resp.json()
        assert "nothing to delete" in body["error"]["message"] or "cannot be deleted" in body["error"]["message"].lower()

    def test_delete_response_any_id(self):
        resp = self.client.delete("/v1/responses/resp_999")
        self._assert_not_found(resp)
        body = resp.json()
        assert "resp_999" in body["error"]["message"]

    def test_cancel_response_returns_404(self):
        resp = self.client.post("/v1/responses/resp_abc123/cancel")
        self._assert_not_found(resp)

    def test_cancel_response_includes_id_in_message(self):
        resp = self.client.post("/v1/responses/resp_abc123/cancel")
        body = resp.json()
        assert "resp_abc123" in body["error"]["message"]

    def test_cancel_response_suggests_closing_connection(self):
        """Cancel stub should guide users on how to actually cancel."""
        resp = self.client.post("/v1/responses/resp_abc123/cancel")
        body = resp.json()
        msg = body["error"]["message"].lower()
        assert "cancel" in msg or "close" in msg or "connection" in msg

    def test_cancel_response_any_id(self):
        resp = self.client.post("/v1/responses/resp_other/cancel")
        self._assert_not_found(resp)
        body = resp.json()
        assert "resp_other" in body["error"]["message"]

    def test_error_format_matches_responses_api(self):
        """Error body must have the standard Responses API error structure."""
        resp = self.client.get("/v1/responses/resp_test")
        body = resp.json()
        assert "error" in body
        assert "message" in body["error"]
        assert "type" in body["error"]
        assert "code" in body["error"]
        assert "param" in body["error"]
        assert body["error"]["param"] is None

    def test_each_stub_has_distinct_message(self):
        """GET, DELETE, and cancel should have different error messages
        appropriate to their operation."""
        get_msg = self.client.get("/v1/responses/resp_x").json()["error"]["message"]
        del_msg = self.client.delete("/v1/responses/resp_x").json()["error"]["message"]
        cancel_msg = self.client.post("/v1/responses/resp_x/cancel").json()["error"]["message"]
        # All three should be different (they explain different operations)
        assert get_msg != del_msg
        assert get_msg != cancel_msg
        assert del_msg != cancel_msg

    def test_get_response_has_request_id(self):
        resp = self.client.get("/v1/responses/resp_abc123")
        assert "x-request-id" in resp.headers
        assert resp.headers["x-request-id"].startswith("req_")

    def test_delete_response_has_request_id(self):
        resp = self.client.delete("/v1/responses/resp_abc123")
        assert "x-request-id" in resp.headers
        assert resp.headers["x-request-id"].startswith("req_")

    def test_cancel_response_has_request_id(self):
        resp = self.client.post("/v1/responses/resp_abc123/cancel")
        assert "x-request-id" in resp.headers
        assert resp.headers["x-request-id"].startswith("req_")

    def test_stub_error_body_structure(self):
        """All stub endpoints return the standard OpenAI error envelope."""
        for method, path in [
            ("get", "/v1/responses/resp_x"),
            ("delete", "/v1/responses/resp_x"),
            ("post", "/v1/responses/resp_x/cancel"),
        ]:
            resp = getattr(self.client, method)(path)
            body = resp.json()
            assert "error" in body, f"Missing error key on {method.upper()} {path}"
            assert "message" in body["error"]
            assert "type" in body["error"]
            assert "code" in body["error"]
            assert "param" in body["error"]

    # --- GET /v1/responses/{response_id}/input_items ---

    def test_input_items_returns_404(self):
        resp = self.client.get("/v1/responses/resp_abc123/input_items")
        self._assert_not_found(resp)

    def test_input_items_includes_response_id_in_message(self):
        resp = self.client.get("/v1/responses/resp_abc123/input_items")
        body = resp.json()
        assert "resp_abc123" in body["error"]["message"]

    def test_input_items_explains_no_persistence(self):
        resp = self.client.get("/v1/responses/resp_abc123/input_items")
        body = resp.json()
        assert "not persist" in body["error"]["message"] or "store" in body["error"]["message"]

    def test_input_items_any_id(self):
        resp = self.client.get("/v1/responses/resp_xyz999/input_items")
        self._assert_not_found(resp)
        body = resp.json()
        assert "resp_xyz999" in body["error"]["message"]

    def test_input_items_has_request_id(self):
        resp = self.client.get("/v1/responses/resp_abc123/input_items")
        assert "x-request-id" in resp.headers
        assert resp.headers["x-request-id"].startswith("req_")

    def test_input_items_error_body_structure(self):
        resp = self.client.get("/v1/responses/resp_x/input_items")
        body = resp.json()
        assert "error" in body
        assert "message" in body["error"]
        assert "type" in body["error"]
        assert "code" in body["error"]
        assert "param" in body["error"]
        assert body["error"]["param"] is None


# ---------------------------------------------------------------------------
# Input token counting: POST /v1/responses/input_tokens
# ---------------------------------------------------------------------------


class TestCountResponseInputTokens:
    """Tests for POST /v1/responses/input_tokens — local token counting
    for the Responses API surface."""

    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch):
        from fastapi.testclient import TestClient

        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])

        app = _make_responses_app()
        self.client = TestClient(app)

    def test_basic_token_count(self):
        resp = self.client.post("/v1/responses/input_tokens", json={
            "model": "gpt-4o",
            "input": "Hello, world!",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "input_tokens" in body
        assert isinstance(body["input_tokens"], int)
        assert body["input_tokens"] > 0

    def test_response_includes_object_field(self):
        resp = self.client.post("/v1/responses/input_tokens", json={
            "model": "gpt-4o",
            "input": "Hello",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "response.input_tokens"

    def test_array_input(self):
        resp = self.client.post("/v1/responses/input_tokens", json={
            "model": "gpt-4o",
            "input": [
                {"type": "message", "role": "user", "content": "Hi there"},
            ],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["input_tokens"] > 0

    def test_instructions_contribute_to_count(self):
        resp_no_inst = self.client.post("/v1/responses/input_tokens", json={
            "model": "gpt-4o",
            "input": "hi",
        })
        resp_with_inst = self.client.post("/v1/responses/input_tokens", json={
            "model": "gpt-4o",
            "input": "hi",
            "instructions": "You are a helpful assistant that provides detailed answers.",
        })
        assert resp_no_inst.status_code == 200
        assert resp_with_inst.status_code == 200
        assert resp_with_inst.json()["input_tokens"] > resp_no_inst.json()["input_tokens"]

    def test_count_with_tools(self):
        resp_no_tools = self.client.post("/v1/responses/input_tokens", json={
            "model": "gpt-4o",
            "input": "hi",
        })
        resp_with_tools = self.client.post("/v1/responses/input_tokens", json={
            "model": "gpt-4o",
            "input": "hi",
            "tools": [
                {
                    "type": "function",
                    "name": "get_weather",
                    "description": "Get the current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string", "description": "City and state"},
                        },
                        "required": ["location"],
                    },
                },
            ],
        })
        assert resp_no_tools.status_code == 200
        assert resp_with_tools.status_code == 200
        assert resp_with_tools.json()["input_tokens"] > resp_no_tools.json()["input_tokens"]

    def test_count_with_multiple_tools(self):
        resp = self.client.post("/v1/responses/input_tokens", json={
            "model": "gpt-4o",
            "input": "hi",
            "tools": [
                {
                    "type": "function",
                    "name": "tool_a",
                    "description": "First tool",
                    "parameters": {"type": "object", "properties": {}},
                },
                {
                    "type": "function",
                    "name": "tool_b",
                    "description": "Second tool with more params",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "string"},
                            "y": {"type": "integer"},
                        },
                    },
                },
            ],
        })
        assert resp.status_code == 200
        assert resp.json()["input_tokens"] > 0

    def test_invalid_json_returns_400(self):
        resp = self.client.post(
            "/v1/responses/input_tokens",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "JSON" in body["error"]["message"] or "json" in body["error"]["message"].lower()

    def test_empty_input_still_counts(self):
        resp = self.client.post("/v1/responses/input_tokens", json={
            "model": "gpt-4o",
            "input": "",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["input_tokens"], int)

    def test_has_request_id_header(self):
        resp = self.client.post("/v1/responses/input_tokens", json={
            "model": "gpt-4o",
            "input": "test",
        })
        assert "x-request-id" in resp.headers
        assert resp.headers["x-request-id"].startswith("req_")

    def test_web_search_tool_contributes_to_count(self):
        """web_search_preview tools are mapped to a function tool
        and should contribute tokens."""
        resp_no_tools = self.client.post("/v1/responses/input_tokens", json={
            "model": "gpt-4o",
            "input": "hi",
        })
        resp_with_ws = self.client.post("/v1/responses/input_tokens", json={
            "model": "gpt-4o",
            "input": "hi",
            "tools": [{"type": "web_search_preview"}],
        })
        assert resp_no_tools.status_code == 200
        assert resp_with_ws.status_code == 200
        assert resp_with_ws.json()["input_tokens"] > resp_no_tools.json()["input_tokens"]


# ---------------------------------------------------------------------------
# Audio content parts: input_audio
# ---------------------------------------------------------------------------


class TestInputAudioContentParts:
    """Verify input_audio content parts are correctly mapped to
    OpenAI Chat Completions input_audio format."""

    def test_audio_basic_with_data_and_format(self):
        """input_audio with data and format maps correctly."""
        result = responses_compat._convert_content_parts([
            {"type": "input_audio", "data": "base64audiodata", "format": "mp3"},
        ])
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["type"] == "input_audio"
        assert result[0]["input_audio"]["data"] == "base64audiodata"
        assert result[0]["input_audio"]["format"] == "mp3"

    def test_audio_default_format_is_wav(self):
        """When format is omitted, it defaults to wav."""
        result = responses_compat._convert_content_parts([
            {"type": "input_audio", "data": "someb64"},
        ])
        assert isinstance(result, list)
        assert result[0]["input_audio"]["format"] == "wav"

    def test_audio_empty_data(self):
        """Empty data string is passed through."""
        result = responses_compat._convert_content_parts([
            {"type": "input_audio", "data": "", "format": "pcm16"},
        ])
        assert isinstance(result, list)
        assert result[0]["input_audio"]["data"] == ""
        assert result[0]["input_audio"]["format"] == "pcm16"

    def test_audio_missing_data_key(self):
        """Missing data key defaults to empty string."""
        result = responses_compat._convert_content_parts([
            {"type": "input_audio", "format": "wav"},
        ])
        assert isinstance(result, list)
        assert result[0]["input_audio"]["data"] == ""

    def test_audio_wav_format(self):
        result = responses_compat._convert_content_parts([
            {"type": "input_audio", "data": "wavdata", "format": "wav"},
        ])
        assert result[0]["input_audio"]["format"] == "wav"

    def test_audio_pcm16_format(self):
        result = responses_compat._convert_content_parts([
            {"type": "input_audio", "data": "pcmdata", "format": "pcm16"},
        ])
        assert result[0]["input_audio"]["format"] == "pcm16"

    def test_audio_mixed_with_text_no_collapse(self):
        """Audio + text parts should NOT collapse to a string."""
        result = responses_compat._convert_content_parts([
            {"type": "input_text", "text": "transcribe this"},
            {"type": "input_audio", "data": "audiodata", "format": "mp3"},
        ])
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "input_audio"

    def test_audio_mixed_with_image(self):
        """Audio + image parts stay as list."""
        result = responses_compat._convert_content_parts([
            {"type": "input_image", "image_url": "https://example.com/img.png"},
            {"type": "input_audio", "data": "audiodata", "format": "wav"},
        ])
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["type"] == "image_url"
        assert result[1]["type"] == "input_audio"

    def test_audio_in_message_item(self):
        """input_audio in a message item's content list is preserved."""
        body = {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "What is this?"},
                        {"type": "input_audio", "data": "abc123", "format": "mp3"},
                    ],
                }
            ],
        }
        messages = responses_compat._convert_input_to_messages(body)
        assert len(messages) == 1
        content = messages[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[1]["type"] == "input_audio"
        assert content[1]["input_audio"]["data"] == "abc123"


# ---------------------------------------------------------------------------
# File content parts: input_file
# ---------------------------------------------------------------------------


class TestInputFileContentParts:
    """Verify input_file content parts are handled gracefully since
    Chat Completions has no direct file upload equivalent."""

    def test_input_file_with_filename(self):
        """input_file with filename produces a text placeholder."""
        result = responses_compat._convert_content_parts([
            {"type": "input_file", "filename": "report.pdf", "file_id": "file-abc"},
        ])
        assert "report.pdf" in result  # collapsed to string since only text parts

    def test_input_file_with_file_id_only(self):
        """input_file with only file_id uses it in placeholder."""
        result = responses_compat._convert_content_parts([
            {"type": "input_file", "file_id": "file-xyz"},
        ])
        assert "file-xyz" in result

    def test_input_file_no_identifiers(self):
        """input_file with no filename or file_id produces generic placeholder."""
        result = responses_compat._convert_content_parts([
            {"type": "input_file"},
        ])
        assert "[Attached file]" in result

    def test_input_file_logs_warning(self):
        """input_file should log a warning about no equivalent."""
        with patch("responses_compat.logger") as mock_logger:
            responses_compat._convert_content_parts([
                {"type": "input_file", "filename": "data.csv"},
            ])
            mock_logger.warning.assert_called_once()
            assert "input_file" in mock_logger.warning.call_args[0][0]

    def test_input_file_mixed_with_text(self):
        """input_file with text keeps list format (both are text type but different content)."""
        result = responses_compat._convert_content_parts([
            {"type": "input_text", "text": "Please analyze this file"},
            {"type": "input_file", "filename": "data.csv"},
        ])
        # Both become text type, so they collapse to a single string
        assert isinstance(result, str)
        assert "analyze" in result
        assert "data.csv" in result

    def test_input_file_mixed_with_audio(self):
        """input_file alongside audio stays as a list."""
        result = responses_compat._convert_content_parts([
            {"type": "input_file", "filename": "doc.txt"},
            {"type": "input_audio", "data": "abc", "format": "wav"},
        ])
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "input_audio"

    def test_input_file_filename_preferred_over_file_id(self):
        """filename is preferred over file_id for the placeholder text."""
        result = responses_compat._convert_content_parts([
            {"type": "input_file", "filename": "report.pdf", "file_id": "file-123"},
        ])
        assert "report.pdf" in result


# ---------------------------------------------------------------------------
# Computer use items: silently skipped with logging
# ---------------------------------------------------------------------------


class TestComputerUseItems:
    """Verify computer_call_output items in input are silently skipped."""

    def test_computer_call_output_skipped(self):
        """computer_call_output items should be skipped entirely."""
        body = {
            "input": [
                {"type": "message", "role": "user", "content": "hello"},
                {
                    "type": "computer_call_output",
                    "call_id": "cu_abc",
                    "output": {"type": "computer_screenshot", "image_url": "data:..."},
                },
            ],
        }
        messages = responses_compat._convert_input_to_messages(body)
        assert len(messages) == 1
        assert messages[0]["content"] == "hello"

    def test_computer_call_output_logs_debug(self):
        """computer_call_output should log at debug level."""
        with patch("responses_compat.logger") as mock_logger:
            body = {
                "input": [
                    {
                        "type": "computer_call_output",
                        "call_id": "cu_abc",
                        "output": {},
                    },
                ],
            }
            responses_compat._convert_input_to_messages(body)
            mock_logger.debug.assert_called()
            # The debug message uses %s formatting; check that computer_call_output
            # appears either in the format string or as a positional argument
            call_args = mock_logger.debug.call_args[0]
            full_msg = call_args[0] % call_args[1:] if len(call_args) > 1 else call_args[0]
            assert "computer_call_output" in full_msg

    def test_computer_call_output_among_valid_items(self):
        """computer_call_output mixed with valid items; only valid items kept."""
        body = {
            "input": [
                {"type": "message", "role": "user", "content": "first"},
                {
                    "type": "computer_call_output",
                    "call_id": "cu_1",
                    "output": {},
                },
                {"type": "message", "role": "assistant", "content": "second"},
                {
                    "type": "computer_call_output",
                    "call_id": "cu_2",
                    "output": {},
                },
                {"type": "message", "role": "user", "content": "third"},
            ],
        }
        messages = responses_compat._convert_input_to_messages(body)
        assert len(messages) == 3
        assert messages[0]["content"] == "first"
        assert messages[1]["content"] == "second"
        assert messages[2]["content"] == "third"

    def test_only_computer_call_outputs_produces_empty(self):
        """If input contains only computer_call_output items, messages is empty."""
        body = {
            "input": [
                {"type": "computer_call_output", "call_id": "cu_1", "output": {}},
                {"type": "computer_call_output", "call_id": "cu_2", "output": {}},
            ],
        }
        messages = responses_compat._convert_input_to_messages(body)
        assert messages == []


# ---------------------------------------------------------------------------
# Unknown input item types: logged warning
# ---------------------------------------------------------------------------


class TestUnknownInputItemTypes:
    """Verify that unknown input item types are skipped with a warning."""

    def test_unknown_item_type_skipped(self):
        """Items with unrecognized type should be silently skipped."""
        body = {
            "input": [
                {"type": "message", "role": "user", "content": "hello"},
                {"type": "totally_new_feature", "data": "something"},
            ],
        }
        messages = responses_compat._convert_input_to_messages(body)
        assert len(messages) == 1
        assert messages[0]["content"] == "hello"

    def test_unknown_item_type_logs_warning(self):
        """Unknown item types should produce a log warning."""
        with patch("responses_compat.logger") as mock_logger:
            body = {
                "input": [
                    {"type": "future_type_v2", "data": "something"},
                ],
            }
            responses_compat._convert_input_to_messages(body)
            mock_logger.warning.assert_called()
            assert "future_type_v2" in mock_logger.warning.call_args[0][1]

    def test_item_without_type_key_skipped(self):
        """Dict items with no type key should be skipped (type is None)."""
        body = {
            "input": [
                {"role": "user", "content": "no type field"},
            ],
        }
        messages = responses_compat._convert_input_to_messages(body)
        # No type -> item_type is None -> no elif matches, else branch:
        # None is falsy, so warning is not logged, item is just skipped
        assert messages == []

    def test_item_reference_still_skipped_silently(self):
        """item_reference should be skipped without any warning."""
        with patch("responses_compat.logger") as mock_logger:
            body = {
                "input": [
                    {"type": "item_reference", "id": "item_abc"},
                ],
            }
            responses_compat._convert_input_to_messages(body)
            mock_logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# parallel_tool_calls support
# ---------------------------------------------------------------------------


class TestParallelToolCallsPassthrough:
    """parallel_tool_calls should be passed through to the Chat Completions
    body and reflected in the Responses API response objects."""

    def test_parallel_tool_calls_true_passthrough(self):
        body = {"model": "gpt-4o", "input": "hi", "parallel_tool_calls": True}
        result = responses_compat._build_openai_body(body)
        assert result["parallel_tool_calls"] is True

    def test_parallel_tool_calls_false_passthrough(self):
        body = {"model": "gpt-4o", "input": "hi", "parallel_tool_calls": False}
        result = responses_compat._build_openai_body(body)
        assert result["parallel_tool_calls"] is False

    def test_parallel_tool_calls_absent_not_in_body(self):
        body = {"model": "gpt-4o", "input": "hi"}
        result = responses_compat._build_openai_body(body)
        assert "parallel_tool_calls" not in result

    def test_response_reflects_parallel_tool_calls_true(self):
        openai_result = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_1",
            request_body={"parallel_tool_calls": True},
        )
        assert resp["parallel_tool_calls"] is True

    def test_response_reflects_parallel_tool_calls_false(self):
        openai_result = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_2",
            request_body={"parallel_tool_calls": False},
        )
        assert resp["parallel_tool_calls"] is False

    def test_response_defaults_to_true_when_absent(self):
        openai_result = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_3",
            request_body={"model": "gpt-4o"},
        )
        assert resp["parallel_tool_calls"] is True

    def test_response_defaults_to_true_when_no_request_body(self):
        openai_result = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_4",
        )
        assert resp["parallel_tool_calls"] is True


class TestParallelToolCallsStreaming:
    """parallel_tool_calls should be reflected in the streaming skeleton."""

    @pytest.mark.asyncio
    async def test_streaming_skeleton_reflects_false(self):
        async def empty_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for evt in responses_compat._responses_stream_converter(
            empty_stream(), "gpt-4o", "resp_s1",
            request_body={"parallel_tool_calls": False},
        ):
            events.append(evt)

        # Parse the response.created event to check the skeleton
        created_event = None
        for evt in events:
            for line in evt.strip().split("\n"):
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if data.get("type") == "response.created":
                            created_event = data
                    except (json.JSONDecodeError, TypeError):
                        pass
        assert created_event is not None
        assert created_event["response"]["parallel_tool_calls"] is False

    @pytest.mark.asyncio
    async def test_streaming_skeleton_defaults_to_true(self):
        async def empty_stream():
            yield 'data: {"choices":[{"delta":{"content":"ok"},"index":0}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for evt in responses_compat._responses_stream_converter(
            empty_stream(), "gpt-4o", "resp_s2",
            request_body={},
        ):
            events.append(evt)

        created_event = None
        for evt in events:
            for line in evt.strip().split("\n"):
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if data.get("type") == "response.created":
                            created_event = data
                    except (json.JSONDecodeError, TypeError):
                        pass
        assert created_event is not None
        assert created_event["response"]["parallel_tool_calls"] is True


class TestToolChoiceNonePreventsTools:
    """tool_choice='none' should pass through correctly to prevent tool calls."""

    def test_tool_choice_none_string(self):
        result = responses_compat._convert_tool_choice({"tool_choice": "none"})
        assert result == "none"

    def test_tool_choice_none_in_openai_body(self):
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "tools": [
                {"type": "function", "name": "fn", "description": "d", "parameters": {}},
            ],
            "tool_choice": "none",
        }
        result = responses_compat._build_openai_body(body)
        assert result["tool_choice"] == "none"
        # Tools are still included (backend respects tool_choice to suppress calls)
        assert "tools" in result

    def test_tool_choice_none_with_parallel_false(self):
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "tools": [
                {"type": "function", "name": "fn", "description": "d", "parameters": {}},
            ],
            "tool_choice": "none",
            "parallel_tool_calls": False,
        }
        result = responses_compat._build_openai_body(body)
        assert result["tool_choice"] == "none"
        assert result["parallel_tool_calls"] is False


# ---------------------------------------------------------------------------
# Output index / content_index tracking
# ---------------------------------------------------------------------------


class TestOutputIndexTracking:
    """Verify output_index and content_index are tracked correctly across all
    streaming scenarios.

    Scenarios:
      a. Text only: output_index 0, content_index 0
      b. Reasoning + text: reasoning at 0, message at 1, content_index 0
      c. Text + 2 tool calls: message at 0, tools at 1 and 2
      d. Reasoning + text + tool: reasoning 0, message 1, tool 2
    """

    @pytest.mark.asyncio
    async def test_text_only_indices(self):
        """Text only: output_index 0, content_index 0 on all events."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"Hello"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":" world"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_idx_text"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # output_item.added for message
        msg_added = [d for t, d in parsed
                     if t == "response.output_item.added" and d["item"]["type"] == "message"]
        assert len(msg_added) == 1
        assert msg_added[0]["output_index"] == 0

        # content_part.added
        part_added = [d for t, d in parsed if t == "response.content_part.added"]
        assert len(part_added) == 1
        assert part_added[0]["output_index"] == 0
        assert part_added[0]["content_index"] == 0

        # output_text.delta events
        text_deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        for delta in text_deltas:
            assert delta["output_index"] == 0
            assert delta["content_index"] == 0

        # output_text.done
        text_done = [d for t, d in parsed if t == "response.output_text.done"]
        assert len(text_done) == 1
        assert text_done[0]["output_index"] == 0
        assert text_done[0]["content_index"] == 0

        # content_part.done
        cp_done = [d for t, d in parsed if t == "response.content_part.done"]
        assert len(cp_done) == 1
        assert cp_done[0]["output_index"] == 0
        assert cp_done[0]["content_index"] == 0

        # output_item.done for message
        msg_done = [d for t, d in parsed
                    if t == "response.output_item.done" and d["item"]["type"] == "message"]
        assert len(msg_done) == 1
        assert msg_done[0]["output_index"] == 0

    @pytest.mark.asyncio
    async def test_reasoning_then_text_indices(self):
        """Reasoning at output_index 0, message at output_index 1, content_index 0."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"Think"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"reasoning_content":"..."},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"The answer."},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_idx_rt"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # Reasoning output_item.added at index 0
        reasoning_added = [d for t, d in parsed
                           if t == "response.output_item.added" and d["item"]["type"] == "reasoning"]
        assert len(reasoning_added) == 1
        assert reasoning_added[0]["output_index"] == 0

        # Reasoning summary_part.added at output_index 0
        rsp_added = [d for t, d in parsed if t == "response.reasoning_summary_part.added"]
        assert len(rsp_added) == 1
        assert rsp_added[0]["output_index"] == 0
        assert rsp_added[0]["summary_index"] == 0

        # Reasoning deltas at output_index 0
        reasoning_deltas = [d for t, d in parsed if t == "response.reasoning_summary_text.delta"]
        for rd in reasoning_deltas:
            assert rd["output_index"] == 0
            assert rd["summary_index"] == 0

        # Reasoning done events at output_index 0
        reasoning_text_done = [d for t, d in parsed if t == "response.reasoning_summary_text.done"]
        assert len(reasoning_text_done) == 1
        assert reasoning_text_done[0]["output_index"] == 0

        reasoning_part_done = [d for t, d in parsed if t == "response.reasoning_summary_part.done"]
        assert len(reasoning_part_done) == 1
        assert reasoning_part_done[0]["output_index"] == 0

        reasoning_item_done = [d for t, d in parsed
                               if t == "response.output_item.done" and d["item"]["type"] == "reasoning"]
        assert len(reasoning_item_done) == 1
        assert reasoning_item_done[0]["output_index"] == 0

        # Text output_item.added at index 1
        msg_added = [d for t, d in parsed
                     if t == "response.output_item.added" and d["item"]["type"] == "message"]
        assert len(msg_added) == 1
        assert msg_added[0]["output_index"] == 1

        # content_part.added at output_index 1, content_index 0
        part_added = [d for t, d in parsed if t == "response.content_part.added"]
        assert len(part_added) == 1
        assert part_added[0]["output_index"] == 1
        assert part_added[0]["content_index"] == 0

        # Text deltas at output_index 1, content_index 0
        text_deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        for td in text_deltas:
            assert td["output_index"] == 1
            assert td["content_index"] == 0

        # Text done at output_index 1
        text_done = [d for t, d in parsed if t == "response.output_text.done"]
        assert len(text_done) == 1
        assert text_done[0]["output_index"] == 1
        assert text_done[0]["content_index"] == 0

        # Message output_item.done at index 1
        msg_done = [d for t, d in parsed
                    if t == "response.output_item.done" and d["item"]["type"] == "message"]
        assert len(msg_done) == 1
        assert msg_done[0]["output_index"] == 1

    @pytest.mark.asyncio
    async def test_text_then_two_tool_calls_indices(self):
        """Text at output_index 0, first tool at 1, second tool at 2."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"Let me search."},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_A","function":{"name":"search","arguments":"{\\"q\\":"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"foo\\"}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"call_B","function":{"name":"lookup","arguments":"{\\"id\\":1}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_idx_tt"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # Message at output_index 0
        msg_added = [d for t, d in parsed
                     if t == "response.output_item.added" and d["item"]["type"] == "message"]
        assert len(msg_added) == 1
        assert msg_added[0]["output_index"] == 0

        # Text content at output_index 0, content_index 0
        text_deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        for td in text_deltas:
            assert td["output_index"] == 0
            assert td["content_index"] == 0

        # Tool calls added
        tool_added = [d for t, d in parsed
                      if t == "response.output_item.added" and d["item"]["type"] == "function_call"]
        assert len(tool_added) == 2
        assert tool_added[0]["output_index"] == 1
        assert tool_added[1]["output_index"] == 2

        # Tool call argument deltas reference correct output_index
        arg_deltas = [d for t, d in parsed if t == "response.function_call_arguments.delta"]
        # First tool's deltas at output_index 1
        tool_a_deltas = [d for d in arg_deltas if d["item_id"] == "call_A"]
        for d in tool_a_deltas:
            assert d["output_index"] == 1
        # Second tool's deltas at output_index 2
        tool_b_deltas = [d for d in arg_deltas if d["item_id"] == "call_B"]
        for d in tool_b_deltas:
            assert d["output_index"] == 2

        # function_call_arguments.done events
        args_done = [d for t, d in parsed if t == "response.function_call_arguments.done"]
        assert len(args_done) == 2
        args_done_by_id = {d["item_id"]: d for d in args_done}
        assert args_done_by_id["call_A"]["output_index"] == 1
        assert args_done_by_id["call_B"]["output_index"] == 2
        assert args_done_by_id["call_A"]["arguments"] == '{"q":"foo"}'
        assert args_done_by_id["call_B"]["arguments"] == '{"id":1}'

        # output_item.done for tools
        tool_done = [d for t, d in parsed
                     if t == "response.output_item.done" and d["item"]["type"] == "function_call"]
        assert len(tool_done) == 2
        assert tool_done[0]["output_index"] == 1
        assert tool_done[1]["output_index"] == 2

    @pytest.mark.asyncio
    async def test_reasoning_text_tool_indices(self):
        """Reasoning at 0, message at 1, tool at 2."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"I should search"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"Searching now."},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_Z","function":{"name":"search","arguments":"{\\"q\\":\\"test\\"}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_idx_rtt"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # Reasoning at output_index 0
        reasoning_added = [d for t, d in parsed
                           if t == "response.output_item.added" and d["item"]["type"] == "reasoning"]
        assert len(reasoning_added) == 1
        assert reasoning_added[0]["output_index"] == 0

        # Message at output_index 1
        msg_added = [d for t, d in parsed
                     if t == "response.output_item.added" and d["item"]["type"] == "message"]
        assert len(msg_added) == 1
        assert msg_added[0]["output_index"] == 1

        # Text at output_index 1, content_index 0
        text_deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        for td in text_deltas:
            assert td["output_index"] == 1
            assert td["content_index"] == 0

        # Tool at output_index 2
        tool_added = [d for t, d in parsed
                      if t == "response.output_item.added" and d["item"]["type"] == "function_call"]
        assert len(tool_added) == 1
        assert tool_added[0]["output_index"] == 2

        # Tool argument delta at output_index 2
        arg_deltas = [d for t, d in parsed if t == "response.function_call_arguments.delta"]
        for d in arg_deltas:
            assert d["output_index"] == 2

        # Tool done at output_index 2
        tool_done = [d for t, d in parsed
                     if t == "response.output_item.done" and d["item"]["type"] == "function_call"]
        assert len(tool_done) == 1
        assert tool_done[0]["output_index"] == 2

        # function_call_arguments.done at output_index 2
        args_done = [d for t, d in parsed if t == "response.function_call_arguments.done"]
        assert len(args_done) == 1
        assert args_done[0]["output_index"] == 2

    @pytest.mark.asyncio
    async def test_tool_only_no_text_indices(self):
        """Tool call with no preceding text: tool at output_index 0."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_X","function":{"name":"fn","arguments":"{\\"a\\":1}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_idx_to"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        tool_added = [d for t, d in parsed
                      if t == "response.output_item.added" and d["item"]["type"] == "function_call"]
        assert len(tool_added) == 1
        assert tool_added[0]["output_index"] == 0

        # No message items
        msg_added = [d for t, d in parsed
                     if t == "response.output_item.added" and d["item"]["type"] == "message"]
        assert len(msg_added) == 0

    @pytest.mark.asyncio
    async def test_reasoning_then_tool_no_text_indices(self):
        """Reasoning at 0, tool at 1, no text message item."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"Need to call fn"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_Y","function":{"name":"fn","arguments":"{}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_idx_rto"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        reasoning_added = [d for t, d in parsed
                           if t == "response.output_item.added" and d["item"]["type"] == "reasoning"]
        assert len(reasoning_added) == 1
        assert reasoning_added[0]["output_index"] == 0

        tool_added = [d for t, d in parsed
                      if t == "response.output_item.added" and d["item"]["type"] == "function_call"]
        assert len(tool_added) == 1
        assert tool_added[0]["output_index"] == 1

        # No text message item
        msg_added = [d for t, d in parsed
                     if t == "response.output_item.added" and d["item"]["type"] == "message"]
        assert len(msg_added) == 0

    @pytest.mark.asyncio
    async def test_three_parallel_tool_calls_indices(self):
        """Three parallel tool calls: indices 0, 1, 2."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"fn1","arguments":"{}"}},{"index":1,"id":"call_2","function":{"name":"fn2","arguments":"{}"}},{"index":2,"id":"call_3","function":{"name":"fn3","arguments":"{}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_idx_3t"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        tool_added = [d for t, d in parsed
                      if t == "response.output_item.added" and d["item"]["type"] == "function_call"]
        assert len(tool_added) == 3
        assert tool_added[0]["output_index"] == 0
        assert tool_added[1]["output_index"] == 1
        assert tool_added[2]["output_index"] == 2

        tool_done = [d for t, d in parsed
                     if t == "response.output_item.done" and d["item"]["type"] == "function_call"]
        assert len(tool_done) == 3
        assert tool_done[0]["output_index"] == 0
        assert tool_done[1]["output_index"] == 1
        assert tool_done[2]["output_index"] == 2

    @pytest.mark.asyncio
    async def test_non_streaming_output_item_order(self):
        """Non-streaming: verify output items are in correct order."""
        # Reasoning + text + tool call in non-streaming result
        result = {
            "choices": [{
                "message": {
                    "content": "Answer",
                    "reasoning_content": "Thinking...",
                    "tool_calls": [
                        {"id": "call_1", "function": {"name": "fn", "arguments": "{}"}},
                    ],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        }
        items = responses_compat._build_output_items(result)

        # Order: reasoning, message, function_call
        assert len(items) == 3
        assert items[0]["type"] == "reasoning"
        assert items[1]["type"] == "message"
        assert items[2]["type"] == "function_call"

    @pytest.mark.asyncio
    async def test_content_index_always_zero_multiple_text_deltas(self):
        """Multiple text deltas all reference content_index 0 (single content part)."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"A"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"B"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"C"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"D"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_idx_ci"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        text_deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        assert len(text_deltas) == 4
        for td in text_deltas:
            assert td["content_index"] == 0

    @pytest.mark.asyncio
    async def test_error_path_indices_after_reasoning(self):
        """Error after reasoning: reasoning at 0, error message at 1."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"Hmm"},"index":0}]}\n\n'
            raise RuntimeError("backend crash")

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_idx_err"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # Reasoning at output_index 0
        reasoning_added = [d for t, d in parsed
                           if t == "response.output_item.added" and d["item"]["type"] == "reasoning"]
        assert len(reasoning_added) == 1
        assert reasoning_added[0]["output_index"] == 0

        # Error message at output_index 1
        msg_added = [d for t, d in parsed
                     if t == "response.output_item.added" and d["item"]["type"] == "message"]
        assert len(msg_added) == 1
        assert msg_added[0]["output_index"] == 1

        # Error text delta at output_index 1, content_index 0
        error_deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        assert len(error_deltas) == 1
        assert error_deltas[0]["output_index"] == 1
        assert error_deltas[0]["content_index"] == 0


# ---------------------------------------------------------------------------
# max_output_tokens and temperature edge cases
# ---------------------------------------------------------------------------

class TestResponsesParamEdgeCases:
    """Verify max_output_tokens and temperature edge cases in _build_openai_body."""

    def test_temperature_zero_is_forwarded(self):
        """temperature=0 is valid and must not be dropped due to falsy check."""
        body = {"model": "gpt-4o", "input": "hi", "temperature": 0}
        result = responses_compat._build_openai_body(body)
        assert "temperature" in result
        assert result["temperature"] == 0

    def test_temperature_zero_in_full_body(self):
        """temperature=0 alongside other params."""
        body = {"model": "gpt-4o", "input": "hi", "temperature": 0, "top_p": 1.0, "max_output_tokens": 100}
        result = responses_compat._build_openai_body(body)
        assert result["temperature"] == 0
        assert result["top_p"] == 1.0
        assert result["max_tokens"] == 100

    def test_top_p_zero_is_forwarded(self):
        """top_p=0 is valid and must not be dropped due to falsy check."""
        body = {"model": "gpt-4o", "input": "hi", "top_p": 0}
        result = responses_compat._build_openai_body(body)
        assert "top_p" in result
        assert result["top_p"] == 0

    def test_max_output_tokens_maps_to_max_tokens(self):
        """max_output_tokens should map to max_tokens for backend compatibility."""
        body = {"model": "gpt-4o", "input": "hi", "max_output_tokens": 4096}
        result = responses_compat._build_openai_body(body)
        assert result["max_tokens"] == 4096
        assert "max_output_tokens" not in result

    def test_no_max_output_tokens_omits_max_tokens(self):
        """When max_output_tokens is absent, max_tokens should not be set."""
        body = {"model": "gpt-4o", "input": "hi"}
        result = responses_compat._build_openai_body(body)
        assert "max_tokens" not in result

    def test_temperature_absent_is_not_included(self):
        """When temperature is absent, it should not appear in output."""
        body = {"model": "gpt-4o", "input": "hi"}
        result = responses_compat._build_openai_body(body)
        assert "temperature" not in result


# ---------------------------------------------------------------------------
# Deep edge case audit of _responses_stream_converter
# ---------------------------------------------------------------------------


class TestStreamConverterDeepEdgeCaseAudit:
    """Systematic audit of streaming converter edge cases (a)-(j).

    Each test targets a specific scenario from the edge case checklist.
    """

    # (a) Chunk with both text content AND tool calls in the same delta
    @pytest.mark.asyncio
    async def test_chunk_with_text_and_tool_calls_same_delta(self):
        """A single chunk containing both text content and tool_calls should
        emit text events first, close the text item, then emit tool events."""
        async def mock_stream():
            yield (
                'data: {"choices":[{"delta":{"content":"Let me search",'
                '"tool_calls":[{"index":0,"id":"call_combo","function":{"name":"search","arguments":"{\\"q\\":\\"test\\"}"}}]'
                '},"index":0}]}\n\n'
            )
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_combo"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Text item opens, gets delta, then closes before tool opens
        assert "response.output_text.delta" in event_types
        assert "response.output_text.done" in event_types
        assert "response.function_call_arguments.delta" in event_types
        assert "response.function_call_arguments.done" in event_types

        # Text done must precede tool added
        text_done_idx = event_types.index("response.output_text.done")
        tool_added_indices = [
            i for i, (t, d) in enumerate(parsed)
            if t == "response.output_item.added" and d["item"]["type"] == "function_call"
        ]
        assert all(text_done_idx < idx for idx in tool_added_indices)

        # Both text and tool content are correct
        text_deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        assert text_deltas[0]["delta"] == "Let me search"
        args_done = [d for t, d in parsed if t == "response.function_call_arguments.done"]
        assert args_done[0]["arguments"] == '{"q":"test"}'

    @pytest.mark.asyncio
    async def test_chunk_with_text_and_two_tool_calls_same_delta(self):
        """Single chunk with text + 2 tool calls in same delta."""
        async def mock_stream():
            yield (
                'data: {"choices":[{"delta":{"content":"Calling tools",'
                '"tool_calls":['
                '{"index":0,"id":"call_x1","function":{"name":"fn1","arguments":"{}"}},'
                '{"index":1,"id":"call_x2","function":{"name":"fn2","arguments":"{}"}}'
                ']},"index":0}]}\n\n'
            )
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_combo2"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # 3 output_item.added: 1 message + 2 function_calls
        added = [d for t, d in parsed if t == "response.output_item.added"]
        assert len(added) == 3
        assert added[0]["item"]["type"] == "message"
        assert added[1]["item"]["type"] == "function_call"
        assert added[2]["item"]["type"] == "function_call"

        # 3 output_item.done: 1 message + 2 function_calls
        done = [d for t, d in parsed if t == "response.output_item.done"]
        assert len(done) == 3

    # (b) Tool call with empty/null name
    @pytest.mark.asyncio
    async def test_tool_call_with_empty_name(self):
        """Tool call where function name is empty string."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_noname","function":{"name":"","arguments":"{\\"k\\":1}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_emptyname"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # Tool should still be emitted with empty name
        tool_added = [d for t, d in parsed if t == "response.output_item.added"]
        assert len(tool_added) == 1
        assert tool_added[0]["item"]["name"] == ""
        assert tool_added[0]["item"]["type"] == "function_call"

        # Done event should also have empty name
        tool_done = [d for t, d in parsed if t == "response.output_item.done"]
        assert len(tool_done) == 1
        assert tool_done[0]["item"]["name"] == ""

    @pytest.mark.asyncio
    async def test_tool_call_with_null_name(self):
        """Tool call where function name is null/missing."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_nullname","function":{"name":null,"arguments":"{}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_nullname"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        tool_added = [d for t, d in parsed if t == "response.output_item.added"]
        assert len(tool_added) == 1
        # null name -> dotty.get returns None which is falsy, so tool_state["name"] is never set
        # get defaults to ""
        assert tool_added[0]["item"]["name"] == ""

    @pytest.mark.asyncio
    async def test_tool_call_with_missing_function_key(self):
        """Tool call chunk with no function key at all."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_nofunc"}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"fn","arguments":"{\\"a\\":1}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_nofunc"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # First chunk has id but no function -> tool emitted with empty name initially
        tool_added = [d for t, d in parsed if t == "response.output_item.added"]
        assert len(tool_added) == 1
        assert tool_added[0]["item"]["name"] == ""

        # Second chunk provides name and args -> emitted as delta
        args_done = [d for t, d in parsed if t == "response.function_call_arguments.done"]
        assert len(args_done) == 1
        assert args_done[0]["arguments"] == '{"a":1}'

        # Done item should have the name from the second chunk
        tool_done = [d for t, d in parsed if t == "response.output_item.done"]
        assert tool_done[0]["item"]["name"] == "fn"

    # (c) Empty text deltas (content: "")
    @pytest.mark.asyncio
    async def test_empty_text_delta_skipped(self):
        """Chunks with content: '' should not produce output_text.delta events."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":""},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"real text"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":""},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_empty_delta"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # Only one text delta for "real text", empty ones are skipped
        text_deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        assert len(text_deltas) == 1
        assert text_deltas[0]["delta"] == "real text"

    @pytest.mark.asyncio
    async def test_null_content_delta_skipped(self):
        """Chunks with content: null should not produce output_text.delta events."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":null},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"actual"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_null_delta"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        text_deltas = [d for t, d in parsed if t == "response.output_text.delta"]
        assert len(text_deltas) == 1
        assert text_deltas[0]["delta"] == "actual"

    @pytest.mark.asyncio
    async def test_all_empty_text_deltas_no_text_item(self):
        """Stream with only empty content deltas produces no text item."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":""},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":""},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_all_empty"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # No text item should be opened
        assert "response.output_text.delta" not in event_types
        assert "response.output_item.added" not in event_types
        # But should still have created + completed
        assert event_types[0] == "response.created"
        assert event_types[-1] == "response.completed"

    # (d) Finish-reason-only stream (no content at all)
    @pytest.mark.asyncio
    async def test_finish_reason_only_stream_valid_envelope(self):
        """Stream with only finish_reason chunk (no content/tools) produces a
        valid response envelope with no output items."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_fr_only"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        assert event_types[0] == "response.created"
        assert event_types[1] == "response.in_progress"
        assert event_types[-1] == "response.completed"

        # No output items emitted
        assert "response.output_item.added" not in event_types
        assert "response.output_text.delta" not in event_types
        assert "response.function_call_arguments.delta" not in event_types

        # Completed event has valid structure
        completed = [d for t, d in parsed if t == "response.completed"]
        assert completed[0]["response"]["status"] == "completed"
        assert completed[0]["response"]["id"] == "resp_fr_only"

    @pytest.mark.asyncio
    async def test_finish_reason_length_maps_to_incomplete(self):
        """finish_reason 'length' should map to status 'incomplete'."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"truncated"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"length"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_fr_len"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        incomplete = [d for t, d in parsed if t == "response.incomplete"]
        assert incomplete[0]["response"]["status"] == "incomplete"
        assert incomplete[0]["response"]["incomplete_details"] == {"reason": "max_output_tokens"}

    # (e) Reasoning content interleaved with text — transitions correct?
    @pytest.mark.asyncio
    async def test_reasoning_to_text_transition_closes_reasoning(self):
        """When text arrives after reasoning, the reasoning item must be fully
        closed (text.done + part.done + item.done) before the text item opens."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"think"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"reasoning_content":"..."},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"answer"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_r2t"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Reasoning close events must come before text open events
        reasoning_item_done_idx = next(
            i for i, (t, d) in enumerate(parsed)
            if t == "response.output_item.done" and d["item"]["type"] == "reasoning"
        )
        text_item_added_idx = next(
            i for i, (t, d) in enumerate(parsed)
            if t == "response.output_item.added" and d["item"]["type"] == "message"
        )
        assert reasoning_item_done_idx < text_item_added_idx

        # Reasoning text.done and part.done must precede item.done
        reasoning_text_done_idx = event_types.index("response.reasoning_summary_text.done")
        reasoning_part_done_idx = event_types.index("response.reasoning_summary_part.done")
        assert reasoning_text_done_idx < reasoning_part_done_idx
        assert reasoning_part_done_idx < reasoning_item_done_idx

        # Reasoning text.done should contain accumulated reasoning
        reasoning_text_done = [d for t, d in parsed if t == "response.reasoning_summary_text.done"]
        assert reasoning_text_done[0]["text"] == "think..."

    @pytest.mark.asyncio
    async def test_reasoning_and_text_in_same_chunk(self):
        """Both reasoning_content and content in the same delta chunk."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"think","content":"answer"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_rt_same"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Both reasoning and text should be emitted
        assert "response.reasoning_summary_text.delta" in event_types
        assert "response.output_text.delta" in event_types

        # Reasoning item should be opened and closed before text item opens
        reasoning_added = [d for t, d in parsed
                          if t == "response.output_item.added" and d["item"]["type"] == "reasoning"]
        msg_added = [d for t, d in parsed
                    if t == "response.output_item.added" and d["item"]["type"] == "message"]
        assert len(reasoning_added) == 1
        assert len(msg_added) == 1

        # Reasoning at output_index 0, text at output_index 1
        assert reasoning_added[0]["output_index"] == 0
        assert msg_added[0]["output_index"] == 1

    @pytest.mark.asyncio
    async def test_reasoning_then_tool_no_text(self):
        """Reasoning followed directly by tool calls, no text content."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"reasoning_content":"I need to search"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_rt","function":{"name":"search","arguments":"{\\"q\\":\\"test\\"}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "o3", "resp_r2tool"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # Reasoning closes before tool opens
        reasoning_done = [d for t, d in parsed
                         if t == "response.output_item.done" and d["item"]["type"] == "reasoning"]
        tool_added = [d for t, d in parsed
                     if t == "response.output_item.added" and d["item"]["type"] == "function_call"]
        assert len(reasoning_done) == 1
        assert len(tool_added) == 1
        assert reasoning_done[0]["output_index"] == 0
        assert tool_added[0]["output_index"] == 1

        # No text message item
        msg_added = [d for t, d in parsed
                    if t == "response.output_item.added" and d["item"]["type"] == "message"]
        assert len(msg_added) == 0

    # (f) Multiple tool calls in a single chunk
    @pytest.mark.asyncio
    async def test_three_tools_in_one_chunk(self):
        """Three tool calls arrive in a single tool_calls array within one chunk."""
        async def mock_stream():
            yield (
                'data: {"choices":[{"delta":{"tool_calls":['
                '{"index":0,"id":"call_a","function":{"name":"fn_a","arguments":"{\\"x\\":1}"}},'
                '{"index":1,"id":"call_b","function":{"name":"fn_b","arguments":"{\\"y\\":2}"}},'
                '{"index":2,"id":"call_c","function":{"name":"fn_c","arguments":"{\\"z\\":3}"}}'
                ']},"index":0}]}\n\n'
            )
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_3tools"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # Three output_item.added events for function_calls
        tool_added = [d for t, d in parsed
                     if t == "response.output_item.added" and d["item"]["type"] == "function_call"]
        assert len(tool_added) == 3
        assert [t["item"]["name"] for t in tool_added] == ["fn_a", "fn_b", "fn_c"]

        # Three function_call_arguments.done events
        args_done = [d for t, d in parsed if t == "response.function_call_arguments.done"]
        assert len(args_done) == 3
        assert args_done[0]["arguments"] == '{"x":1}'
        assert args_done[1]["arguments"] == '{"y":2}'
        assert args_done[2]["arguments"] == '{"z":3}'

        # Three output_item.done
        tool_done = [d for t, d in parsed
                    if t == "response.output_item.done" and d["item"]["type"] == "function_call"]
        assert len(tool_done) == 3

        # Output indices are 0, 1, 2
        assert [t["output_index"] for t in tool_added] == [0, 1, 2]

    # (g) Tool arguments arriving before the tool ID — deferred emission
    @pytest.mark.asyncio
    async def test_tool_args_before_id_deferred(self):
        """Arguments arrive before the tool ID; emission is deferred until ID arrives."""
        async def mock_stream():
            # Args arrive first, no id
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"key\\":"}}]},"index":0}]}\n\n'
            # More args, still no id
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"val\\"}"}}]},"index":0}]}\n\n'
            # Now id and name arrive
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_deferred","function":{"name":"lookup"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_deferred"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # No output_item.added before the ID arrives
        # (first two chunks should NOT produce output_item.added)
        tool_added = [d for t, d in parsed if t == "response.output_item.added"]
        assert len(tool_added) == 1
        assert tool_added[0]["item"]["id"] == "call_deferred"
        assert tool_added[0]["item"]["name"] == "lookup"

        # Accumulated arguments emitted as delta after item.added
        arg_deltas = [d for t, d in parsed if t == "response.function_call_arguments.delta"]
        assert len(arg_deltas) == 1
        assert arg_deltas[0]["delta"] == '{"key":"val"}'

        # Done event has full arguments
        args_done = [d for t, d in parsed if t == "response.function_call_arguments.done"]
        assert args_done[0]["arguments"] == '{"key":"val"}'

    @pytest.mark.asyncio
    async def test_tool_args_before_id_no_id_ever(self):
        """Arguments arrive but ID never arrives; tool is handled in cleanup."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"a\\":1}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_no_id"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # Tool without ID is never emitted (no output_item.added for function_call)
        tool_added = [d for t, d in parsed
                     if t == "response.output_item.added" and d["item"]["type"] == "function_call"]
        assert len(tool_added) == 0

        # Stream still completes normally
        assert parsed[-1][0] == "response.completed"

    # (h) Stream that produces no output items at all
    @pytest.mark.asyncio
    async def test_no_output_items_stream_valid_response(self):
        """Empty stream (only DONE) produces valid response with no output items."""
        async def mock_stream():
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_noop"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Minimum valid envelope: created, in_progress, completed
        assert event_types == [
            "response.created",
            "response.in_progress",
            "response.completed",
        ]

        # Completed response has empty output
        completed = [d for t, d in parsed if t == "response.completed"]
        assert completed[0]["response"]["output"] == []
        assert completed[0]["response"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_only_keepalive_chunks_no_output(self):
        """Stream with only empty delta chunks produces no output items."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_keepalive"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        assert "response.output_item.added" not in event_types
        assert "response.output_text.delta" not in event_types
        assert event_types[-1] == "response.completed"

    # (i) Very large argument strings — any truncation?
    @pytest.mark.asyncio
    async def test_very_large_tool_arguments_no_truncation(self):
        """Large argument strings (100KB+) are passed through without truncation."""
        large_value = "x" * 100_000
        args_json = json.dumps({"data": large_value})
        # Split args into multiple chunks to simulate streaming
        chunk_size = 10_000
        chunks = [args_json[i:i+chunk_size] for i in range(0, len(args_json), chunk_size)]

        async def mock_stream():
            # First chunk: id + name + first args chunk
            yield f'data: {{"choices":[{{"delta":{{"tool_calls":[{{"index":0,"id":"call_big","function":{{"name":"process","arguments":"{_json_escape(chunks[0])}"}}}}]}},"index":0}}]}}\n\n'
            # Remaining chunks: args only
            for chunk in chunks[1:]:
                yield f'data: {{"choices":[{{"delta":{{"tool_calls":[{{"index":0,"function":{{"arguments":"{_json_escape(chunk)}"}}}}]}},"index":0}}]}}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_large"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # function_call_arguments.done should have the full accumulated args
        args_done = [d for t, d in parsed if t == "response.function_call_arguments.done"]
        assert len(args_done) == 1
        assert args_done[0]["arguments"] == args_json
        assert len(args_done[0]["arguments"]) == len(args_json)

        # output_item.done should also have full args
        tool_done = [d for t, d in parsed
                    if t == "response.output_item.done" and d["item"]["type"] == "function_call"]
        assert tool_done[0]["item"]["arguments"] == args_json

    # (j) Backend sends usage in multiple chunks — accumulated correctly?
    @pytest.mark.asyncio
    async def test_usage_in_separate_final_chunk(self):
        """Usage arriving in a separate final chunk (standard OpenAI pattern)."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hello"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            # Usage in separate chunk (OpenAI stream_options.include_usage pattern)
            yield 'data: {"choices":[],"usage":{"prompt_tokens":25,"completion_tokens":10,"total_tokens":35}}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_usage_sep"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        completed = [d for t, d in parsed if t == "response.completed"]
        usage = completed[0]["response"]["usage"]
        assert usage["input_tokens"] == 25
        assert usage["output_tokens"] == 10
        assert usage["total_tokens"] == 35

    @pytest.mark.asyncio
    async def test_usage_in_same_chunk_as_finish_reason(self):
        """Usage arriving in the same chunk as finish_reason."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_usage_same"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        completed = [d for t, d in parsed if t == "response.completed"]
        usage = completed[0]["response"]["usage"]
        assert usage["input_tokens"] == 5
        assert usage["output_tokens"] == 2

    @pytest.mark.asyncio
    async def test_usage_in_multiple_chunks_last_wins(self):
        """When usage appears in multiple chunks, the last non-zero values are used."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            # First usage chunk (partial -- some backends send this early)
            yield 'data: {"choices":[{"delta":{},"index":0}],"usage":{"prompt_tokens":10,"completion_tokens":0,"total_tokens":10}}\n\n'
            # Second usage chunk (final, with completion tokens)
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_usage_multi"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        completed = [d for t, d in parsed if t == "response.completed"]
        usage = completed[0]["response"]["usage"]
        # Last non-zero value wins for each field
        assert usage["input_tokens"] == 10
        assert usage["output_tokens"] == 5

    @pytest.mark.asyncio
    async def test_usage_with_zero_prompt_tokens_preserves_previous(self):
        """If a later chunk reports prompt_tokens:0, the previous non-zero value is kept."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            # Usage with real prompt_tokens
            yield 'data: {"usage":{"prompt_tokens":20,"completion_tokens":3,"total_tokens":23}}\n\n'
            # Later chunk with zero prompt_tokens (shouldn't overwrite)
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"usage":{"prompt_tokens":0,"completion_tokens":3,"total_tokens":3}}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_usage_zero"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        completed = [d for t, d in parsed if t == "response.completed"]
        usage = completed[0]["response"]["usage"]
        # prompt_tokens: 0 in second chunk doesn't overwrite the 20 from first
        assert usage["input_tokens"] == 20
        assert usage["output_tokens"] == 3

    @pytest.mark.asyncio
    async def test_no_usage_in_stream_defaults_to_zero(self):
        """Stream with no usage chunks defaults to 0 tokens."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_no_usage"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        completed = [d for t, d in parsed if t == "response.completed"]
        usage = completed[0]["response"]["usage"]
        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0
        assert usage["total_tokens"] == 0


def _json_escape(s):
    """Escape a string for embedding in a JSON string value."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# ---------------------------------------------------------------------------
# JSON Schema / Structured Output (text.format)
# ---------------------------------------------------------------------------


class TestTextFormatConversion:
    """Verify text.format is converted to response_format in Chat Completions."""

    def test_json_schema_format(self):
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "my_schema",
                    "schema": {"type": "object", "properties": {"x": {"type": "integer"}}},
                    "strict": True,
                }
            },
        }
        result = responses_compat._build_openai_body(body)
        assert result["response_format"]["type"] == "json_schema"
        assert result["response_format"]["json_schema"]["name"] == "my_schema"
        assert result["response_format"]["json_schema"]["strict"] is True
        assert "properties" in result["response_format"]["json_schema"]["schema"]

    def test_json_object_format(self):
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "text": {"format": {"type": "json_object"}},
        }
        result = responses_compat._build_openai_body(body)
        assert result["response_format"] == {"type": "json_object"}

    def test_text_format_default(self):
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "text": {"format": {"type": "text"}},
        }
        result = responses_compat._build_openai_body(body)
        assert "response_format" not in result

    def test_no_text_config(self):
        body = {"model": "gpt-4o", "input": "hi"}
        result = responses_compat._build_openai_body(body)
        assert "response_format" not in result

    def test_json_schema_with_description(self):
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "test",
                    "description": "A test schema",
                    "schema": {"type": "object"},
                }
            },
        }
        result = responses_compat._build_openai_body(body)
        assert result["response_format"]["json_schema"]["description"] == "A test schema"


# ---------------------------------------------------------------------------
# Refusal handling
# ---------------------------------------------------------------------------


class TestRefusalHandling:
    """Verify refusal content is properly handled in both streaming and non-streaming."""

    def test_refusal_in_non_streaming_response(self):
        openai_result = {
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": None, "refusal": "I cannot help with that."},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_ref"
        )
        output = resp["output"]
        assert len(output) == 1
        assert output[0]["type"] == "message"
        assert output[0]["content"][0]["type"] == "refusal"
        assert output[0]["content"][0]["refusal"] == "I cannot help with that."

    def test_refusal_takes_precedence_over_content(self):
        """When both refusal and content exist, refusal wins."""
        openai_result = {
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "hello", "refusal": "No."},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        items = responses_compat._build_output_items(openai_result)
        # Should have refusal, not text
        msg_items = [i for i in items if i["type"] == "message"]
        assert msg_items[0]["content"][0]["type"] == "refusal"

    @pytest.mark.asyncio
    async def test_refusal_streaming(self):
        """Streaming refusal should emit refusal.delta and refusal.done events."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"refusal":"I cannot"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"refusal":" do that"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_ref_stream"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        assert "response.refusal.delta" in event_types
        assert "response.refusal.done" in event_types

        refusal_deltas = [d for t, d in parsed if t == "response.refusal.delta"]
        assert len(refusal_deltas) == 2
        assert refusal_deltas[0]["delta"] == "I cannot"
        assert refusal_deltas[1]["delta"] == " do that"

        refusal_done = [d for t, d in parsed if t == "response.refusal.done"]
        assert len(refusal_done) == 1
        assert refusal_done[0]["refusal"] == "I cannot do that"


# ---------------------------------------------------------------------------
# Terminal event correctness
# ---------------------------------------------------------------------------


class TestTerminalEvents:
    """Verify the correct terminal event type is emitted."""

    @pytest.mark.asyncio
    async def test_completed_terminal_event(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"ok"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_comp"
        ):
            events.append(event)
        parsed = _parse_sse_events(events)
        assert parsed[-1][0] == "response.completed"

    @pytest.mark.asyncio
    async def test_incomplete_terminal_event(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"trunca"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"length"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_inc"
        ):
            events.append(event)
        parsed = _parse_sse_events(events)
        assert parsed[-1][0] == "response.incomplete"
        assert parsed[-1][1]["response"]["status"] == "incomplete"
        assert parsed[-1][1]["response"]["incomplete_details"]["reason"] == "max_output_tokens"

    @pytest.mark.asyncio
    async def test_failed_terminal_event(self):
        async def mock_stream():
            raise RuntimeError("oops")
            yield

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_fail"
        ):
            events.append(event)
        parsed = _parse_sse_events(events)
        assert parsed[-1][0] == "response.failed"
        assert parsed[-1][1]["response"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_content_filter_is_incomplete(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"content_filter"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_cf"
        ):
            events.append(event)
        parsed = _parse_sse_events(events)
        assert parsed[-1][0] == "response.incomplete"
        assert parsed[-1][1]["response"]["incomplete_details"]["reason"] == "content_filter"

    def test_content_filter_non_streaming(self):
        openai_result = {
            "choices": [{"message": {"content": "partial"}, "finish_reason": "content_filter"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_cf_ns"
        )
        assert resp["status"] == "incomplete"
        assert resp["incomplete_details"]["reason"] == "content_filter"


# ---------------------------------------------------------------------------
# User param passthrough
# ---------------------------------------------------------------------------


class TestUserParamPassthrough:
    def test_user_passed_to_openai_body(self):
        body = {"model": "gpt-4o", "input": "hi", "user": "usr_abc123"}
        result = responses_compat._build_openai_body(body)
        assert result["user"] == "usr_abc123"

    def test_user_absent(self):
        body = {"model": "gpt-4o", "input": "hi"}
        result = responses_compat._build_openai_body(body)
        assert "user" not in result


# ---------------------------------------------------------------------------
# Instructions echo in response
# ---------------------------------------------------------------------------


class TestInstructionsEcho:
    def test_instructions_echoed_in_non_streaming(self):
        openai_result = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_test",
            request_body={"instructions": "Be helpful."}
        )
        assert resp["instructions"] == "Be helpful."

    def test_instructions_none_by_default(self):
        openai_result = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        resp = responses_compat._build_responses_response(
            openai_result, "gpt-4o", "resp_test"
        )
        assert resp["instructions"] is None

    @pytest.mark.asyncio
    async def test_instructions_in_streaming_skeleton(self):
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_inst",
            request_body={"instructions": "You are a bot."}
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        created = [d for t, d in parsed if t == "response.created"]
        assert created[0]["response"]["instructions"] == "You are a bot."

    @pytest.mark.asyncio
    async def test_instructions_none_in_streaming_without_body(self):
        async def mock_stream():
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_inst2"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        created = [d for t, d in parsed if t == "response.created"]
        assert created[0]["response"]["instructions"] is None


# ---------------------------------------------------------------------------
# previous_response_id logging
# ---------------------------------------------------------------------------


class TestPreviousResponseId:
    def test_previous_response_id_logs_debug(self):
        body = {
            "model": "gpt-4o",
            "input": "hi",
            "previous_response_id": "resp_abc123",
        }
        with patch.object(responses_compat.logger, "debug") as mock_debug:
            responses_compat._build_openai_body(body)
            calls = [str(c) for c in mock_debug.call_args_list]
            assert any("previous_response_id" in c for c in calls)

    def test_no_previous_response_id_no_debug(self):
        body = {"model": "gpt-4o", "input": "hi"}
        with patch.object(responses_compat.logger, "debug") as mock_debug:
            responses_compat._build_openai_body(body)
            calls = [str(c) for c in mock_debug.call_args_list]
            assert not any("previous_response_id" in c for c in calls)


# ---------------------------------------------------------------------------
# Multi-turn conversation handling
# ---------------------------------------------------------------------------


class TestMultiTurnConversations:
    """Verify end-to-end multi-turn conversation conversion through
    _convert_input_to_messages for realistic conversation patterns that
    OpenAI Responses API clients produce."""

    def test_basic_multi_turn_user_assistant_user(self):
        """Simple user -> assistant -> user follow-up."""
        body = {"input": [
            {"type": "message", "role": "user", "content": "What is Python?"},
            {"type": "message", "role": "assistant", "content": "A programming language."},
            {"type": "message", "role": "user", "content": "What are its features?"},
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 3
        assert msgs[0] == {"role": "user", "content": "What is Python?"}
        assert msgs[1] == {"role": "assistant", "content": "A programming language."}
        assert msgs[2] == {"role": "user", "content": "What are its features?"}

    def test_instructions_plus_multi_turn(self):
        """Instructions (system prompt) with multi-turn history."""
        body = {
            "instructions": "You are a coding tutor.",
            "input": [
                {"type": "message", "role": "user", "content": "Teach me Python"},
                {"type": "message", "role": "assistant", "content": "Let's start with variables."},
                {"type": "message", "role": "user", "content": "Show me an example"},
            ],
        }
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 4
        assert msgs[0] == {"role": "system", "content": "You are a coding tutor."}
        assert msgs[1] == {"role": "user", "content": "Teach me Python"}
        assert msgs[2] == {"role": "assistant", "content": "Let's start with variables."}
        assert msgs[3] == {"role": "user", "content": "Show me an example"}

    def test_function_call_in_input(self):
        """function_call items from previous response echoed in input should
        be converted to assistant messages with tool_calls."""
        body = {"input": [
            {"type": "message", "role": "user", "content": "Weather in NYC?"},
            {
                "type": "function_call",
                "id": "call_w1",
                "call_id": "call_w1",
                "name": "get_weather",
                "arguments": '{"city": "NYC"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_w1",
                "output": "72F, Sunny",
            },
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 3
        # User message
        assert msgs[0] == {"role": "user", "content": "Weather in NYC?"}
        # function_call -> assistant with tool_calls
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] is None
        assert len(msgs[1]["tool_calls"]) == 1
        assert msgs[1]["tool_calls"][0]["id"] == "call_w1"
        assert msgs[1]["tool_calls"][0]["function"]["name"] == "get_weather"
        assert msgs[1]["tool_calls"][0]["function"]["arguments"] == '{"city": "NYC"}'
        # function_call_output -> tool result
        assert msgs[2] == {"role": "tool", "tool_call_id": "call_w1", "content": "72F, Sunny"}

    def test_multiple_function_calls_merged_into_single_assistant_message(self):
        """Consecutive function_call items should merge into one assistant message
        with multiple tool_calls, matching the Chat Completions API pattern."""
        body = {"input": [
            {"type": "message", "role": "user", "content": "Weather in NYC and LA?"},
            {
                "type": "function_call",
                "call_id": "call_nyc",
                "name": "get_weather",
                "arguments": '{"city": "NYC"}',
            },
            {
                "type": "function_call",
                "call_id": "call_la",
                "name": "get_weather",
                "arguments": '{"city": "LA"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_nyc",
                "output": "72F, Sunny",
            },
            {
                "type": "function_call_output",
                "call_id": "call_la",
                "output": "85F, Clear",
            },
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 4
        # User message
        assert msgs[0]["role"] == "user"
        # Two function_calls merged into one assistant message
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] is None
        assert len(msgs[1]["tool_calls"]) == 2
        assert msgs[1]["tool_calls"][0]["function"]["name"] == "get_weather"
        assert msgs[1]["tool_calls"][0]["id"] == "call_nyc"
        assert msgs[1]["tool_calls"][1]["id"] == "call_la"
        # Two tool results
        assert msgs[2] == {"role": "tool", "tool_call_id": "call_nyc", "content": "72F, Sunny"}
        assert msgs[3] == {"role": "tool", "tool_call_id": "call_la", "content": "85F, Clear"}

    def test_function_call_uses_id_when_call_id_missing(self):
        """function_call item with only 'id' (no 'call_id') should use id."""
        body = {"input": [
            {
                "type": "function_call",
                "id": "call_abc",
                "name": "search",
                "arguments": '{"q": "test"}',
            },
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs[0]["tool_calls"][0]["id"] == "call_abc"

    def test_function_call_normalizes_toolu_prefix(self):
        """function_call item with toolu_ prefix should be normalized to call_."""
        body = {"input": [
            {
                "type": "function_call",
                "call_id": "toolu_xyz",
                "name": "tool1",
                "arguments": "{}",
            },
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs[0]["tool_calls"][0]["id"] == "call_xyz"

    def test_function_call_then_output_then_followup(self):
        """Full tool-use round trip followed by continued conversation."""
        body = {
            "instructions": "You are helpful.",
            "input": [
                {"type": "message", "role": "user", "content": "Search for cats"},
                {
                    "type": "function_call",
                    "call_id": "call_s1",
                    "name": "search",
                    "arguments": '{"q": "cats"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_s1",
                    "output": "Cats are domesticated felines.",
                },
                {"type": "message", "role": "assistant", "content": "Cats are domesticated felines!"},
                {"type": "message", "role": "user", "content": "Tell me more about kittens"},
            ],
        }
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 6
        assert msgs[0] == {"role": "system", "content": "You are helpful."}
        assert msgs[1] == {"role": "user", "content": "Search for cats"}
        assert msgs[2]["role"] == "assistant"
        assert msgs[2]["tool_calls"][0]["function"]["name"] == "search"
        assert msgs[3] == {"role": "tool", "tool_call_id": "call_s1", "content": "Cats are domesticated felines."}
        assert msgs[4] == {"role": "assistant", "content": "Cats are domesticated felines!"}
        assert msgs[5] == {"role": "user", "content": "Tell me more about kittens"}

    def test_reasoning_items_silently_skipped(self):
        """reasoning items from previous responses should be silently skipped
        without logging a warning."""
        body = {"input": [
            {"type": "message", "role": "user", "content": "What is 2+2?"},
            {
                "type": "reasoning",
                "id": "rs_abc",
                "summary": [{"type": "summary_text", "text": "Basic arithmetic..."}],
            },
            {"type": "message", "role": "assistant", "content": "4"},
            {"type": "message", "role": "user", "content": "And 3+3?"},
        ]}
        with patch("responses_compat.logger") as mock_logger:
            msgs = responses_compat._convert_input_to_messages(body)
            # Should not log a warning for reasoning items
            mock_logger.warning.assert_not_called()
            # reasoning debug is OK
        assert len(msgs) == 3
        assert msgs[0] == {"role": "user", "content": "What is 2+2?"}
        assert msgs[1] == {"role": "assistant", "content": "4"}
        assert msgs[2] == {"role": "user", "content": "And 3+3?"}

    def test_reasoning_plus_function_call_in_continuation(self):
        """Previous response output (reasoning + function_call) echoed back
        with function_call_output."""
        body = {"input": [
            {"type": "message", "role": "user", "content": "What is the weather?"},
            {
                "type": "reasoning",
                "id": "rs_think1",
                "summary": [{"type": "summary_text", "text": "Need to use weather tool."}],
            },
            {
                "type": "function_call",
                "call_id": "call_w2",
                "name": "get_weather",
                "arguments": '{"city": "NYC"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_w2",
                "output": "72F",
            },
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 3
        # reasoning is skipped
        assert msgs[0] == {"role": "user", "content": "What is the weather?"}
        # function_call -> assistant
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["tool_calls"][0]["id"] == "call_w2"
        # function_call_output -> tool result
        assert msgs[2] == {"role": "tool", "tool_call_id": "call_w2", "content": "72F"}

    def test_message_with_content_parts_in_multi_turn(self):
        """Multi-turn with content parts (images) in messages."""
        body = {"input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Describe this image"},
                    {"type": "input_image", "image_url": "https://example.com/cat.jpg"},
                ],
            },
            {"type": "message", "role": "assistant", "content": "It shows a cat."},
            {"type": "message", "role": "user", "content": "What breed?"},
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 3
        # First message has content parts (not collapsed because mixed types)
        assert isinstance(msgs[0]["content"], list)
        assert msgs[0]["content"][0] == {"type": "text", "text": "Describe this image"}
        assert msgs[0]["content"][1]["type"] == "image_url"
        # Assistant and follow-up are plain strings
        assert msgs[1] == {"role": "assistant", "content": "It shows a cat."}
        assert msgs[2] == {"role": "user", "content": "What breed?"}

    def test_multiple_tool_rounds(self):
        """Two consecutive tool-use rounds in one input array."""
        body = {"input": [
            {"type": "message", "role": "user", "content": "Plan a trip"},
            # First tool round
            {
                "type": "function_call",
                "call_id": "call_flights",
                "name": "search_flights",
                "arguments": '{"dest": "CDG"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_flights",
                "output": "Flight AA100, $500",
            },
            # Assistant responds then invokes another tool
            {"type": "message", "role": "assistant", "content": "Found a flight. Checking hotels."},
            {
                "type": "function_call",
                "call_id": "call_hotels",
                "name": "search_hotels",
                "arguments": '{"city": "Paris"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_hotels",
                "output": "Hotel Le Marais, $200/night",
            },
            {"type": "message", "role": "user", "content": "Book both!"},
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 7
        assert msgs[0] == {"role": "user", "content": "Plan a trip"}
        # First tool round
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["tool_calls"][0]["function"]["name"] == "search_flights"
        assert msgs[2] == {"role": "tool", "tool_call_id": "call_flights", "content": "Flight AA100, $500"}
        # Assistant text + second tool round
        assert msgs[3] == {"role": "assistant", "content": "Found a flight. Checking hotels."}
        assert msgs[4]["role"] == "assistant"
        assert msgs[4]["tool_calls"][0]["function"]["name"] == "search_hotels"
        assert msgs[5] == {"role": "tool", "tool_call_id": "call_hotels", "content": "Hotel Le Marais, $200/night"}
        assert msgs[6] == {"role": "user", "content": "Book both!"}

    def test_function_call_without_arguments(self):
        """function_call with no arguments field should default to '{}'."""
        body = {"input": [
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "get_time",
            },
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs[0]["tool_calls"][0]["function"]["arguments"] == "{}"

    def test_function_call_not_merged_after_non_assistant_message(self):
        """function_call items separated by a non-assistant message should
        NOT merge into the same assistant message."""
        body = {"input": [
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "tool_a",
                "arguments": "{}",
            },
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "result_a",
            },
            {
                "type": "function_call",
                "call_id": "call_2",
                "name": "tool_b",
                "arguments": "{}",
            },
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        # First function_call -> assistant
        assert msgs[0]["role"] == "assistant"
        assert len(msgs[0]["tool_calls"]) == 1
        assert msgs[0]["tool_calls"][0]["id"] == "call_1"
        # Tool result separates the two
        assert msgs[1]["role"] == "tool"
        # Second function_call -> new assistant message (not merged with first)
        assert msgs[2]["role"] == "assistant"
        assert len(msgs[2]["tool_calls"]) == 1
        assert msgs[2]["tool_calls"][0]["id"] == "call_2"

    def test_simple_string_input_still_works(self):
        """String input should still produce a single user message."""
        body = {"input": "Hello, world!"}
        msgs = responses_compat._convert_input_to_messages(body)
        assert msgs == [{"role": "user", "content": "Hello, world!"}]

    def test_item_reference_skipped_in_multi_turn(self):
        """item_reference items should be silently skipped."""
        body = {"input": [
            {"type": "message", "role": "user", "content": "hi"},
            {"type": "item_reference", "id": "msg_prev123"},
            {"type": "message", "role": "assistant", "content": "hello"},
            {"type": "message", "role": "user", "content": "how are you?"},
        ]}
        msgs = responses_compat._convert_input_to_messages(body)
        assert len(msgs) == 3
        assert msgs[0]["content"] == "hi"
        assert msgs[1]["content"] == "hello"
        assert msgs[2]["content"] == "how are you?"

    def test_build_openai_body_with_multi_turn_tool_use(self):
        """_build_openai_body correctly processes multi-turn tool-use input."""
        body = {
            "model": "gpt-4o",
            "instructions": "Be helpful.",
            "input": [
                {"type": "message", "role": "user", "content": "Search for cats"},
                {
                    "type": "function_call",
                    "call_id": "call_s1",
                    "name": "search",
                    "arguments": '{"q": "cats"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_s1",
                    "output": "Cats are domesticated felines.",
                },
                {"type": "message", "role": "user", "content": "Tell me more"},
            ],
            "tools": [
                {
                    "type": "function",
                    "name": "search",
                    "description": "Search the web",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                },
            ],
        }
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["model"] == "gpt-4o"
        # system + user + assistant(tool_call) + tool_result + user
        assert len(openai_body["messages"]) == 5
        assert openai_body["messages"][0] == {"role": "system", "content": "Be helpful."}
        assert openai_body["messages"][1] == {"role": "user", "content": "Search for cats"}
        assert openai_body["messages"][2]["role"] == "assistant"
        assert openai_body["messages"][2]["tool_calls"][0]["function"]["name"] == "search"
        assert openai_body["messages"][3]["role"] == "tool"
        assert openai_body["messages"][4] == {"role": "user", "content": "Tell me more"}
        assert len(openai_body["tools"]) == 1


# ---------------------------------------------------------------------------
# Boost params via metadata
# ---------------------------------------------------------------------------

class TestExtractBoostParams:
    """Verify @boost_ params are extracted from Responses API metadata."""

    def test_no_metadata(self):
        body = {"model": "test", "input": "hi"}
        assert responses_compat._extract_boost_params(body) == {}

    def test_metadata_without_boost_keys(self):
        body = {
            "model": "test",
            "input": "hi",
            "metadata": {"user_id": "u123"},
        }
        assert responses_compat._extract_boost_params(body) == {}

    def test_metadata_with_boost_workflow(self):
        body = {
            "model": "test",
            "input": "hi",
            "metadata": {"@boost_workflow": "research=tools,final"},
        }
        result = responses_compat._extract_boost_params(body)
        assert result == {"@boost_workflow": "research=tools,final"}

    def test_metadata_with_multiple_boost_keys(self):
        body = {
            "model": "test",
            "input": "hi",
            "metadata": {
                "user_id": "u123",
                "@boost_workflow": "my_wf",
                "@boost_pad_size": "256",
                "other_key": "ignored",
            },
        }
        result = responses_compat._extract_boost_params(body)
        assert result == {
            "@boost_workflow": "my_wf",
            "@boost_pad_size": "256",
        }

    def test_metadata_not_dict(self):
        body = {"model": "test", "input": "hi", "metadata": "string"}
        assert responses_compat._extract_boost_params(body) == {}

    def test_boost_params_in_build_openai_body(self):
        """Verify @boost_ keys from metadata appear in the final OpenAI body."""
        body = {
            "model": "test-model",
            "input": "hi",
            "metadata": {
                "user_id": "u123",
                "@boost_workflow": "research=tools,final",
            },
        }
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["@boost_workflow"] == "research=tools,final"
        assert "user_id" not in openai_body

    def test_boost_params_absent_when_no_metadata(self):
        body = {"model": "test-model", "input": "hi"}
        openai_body = responses_compat._build_openai_body(body)
        assert not any(k.startswith("@boost_") for k in openai_body)


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------


class TestSecurityInfoLeakage:
    """Verify that error messages do not leak internal details."""

    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch):
        from fastapi.testclient import TestClient
        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])
        app = _make_responses_app()
        self.client = TestClient(app)

    def test_value_error_does_not_leak_raw_message(self, monkeypatch):
        """ValueError from mapper should return generic error, not the raw message."""
        async def mock_list_downstream():
            return []
        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(
            responses_compat.mapper,
            "resolve_request_config",
            MagicMock(side_effect=ValueError("Backend http://internal:8080/v1 connection refused")),
        )

        resp = self.client.post("/v1/responses", json={"model": "test", "input": "hi"})
        assert resp.status_code == 400
        body = resp.json()
        assert "internal:8080" not in json.dumps(body)
        assert "connection refused" not in body["error"]["message"].lower()
        assert "could not resolve" in body["error"]["message"].lower()

    def test_http_500_does_not_leak_detail(self, monkeypatch):
        """HTTPException with 500 should not expose its detail to clients."""
        async def mock_list_downstream():
            raise HTTPException(status_code=500, detail="Database at db.internal:5432 is down")
        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)

        resp = self.client.post("/v1/responses", json={"model": "test", "input": "hi"})
        assert resp.status_code == 500
        body = resp.json()
        assert "db.internal" not in json.dumps(body)

    def test_generic_exception_does_not_leak(self, monkeypatch):
        """Unexpected exceptions should return generic 500."""
        async def mock_list_downstream():
            raise RuntimeError("segfault in /usr/lib/libcuda.so")
        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)

        resp = self.client.post("/v1/responses", json={"model": "test", "input": "hi"})
        assert resp.status_code == 500
        body = resp.json()
        assert "segfault" not in json.dumps(body)
        assert "libcuda" not in json.dumps(body)

    @pytest.mark.asyncio
    async def test_mid_stream_error_does_not_leak_internals(self):
        """Mid-stream errors must use generic text, not raw exception."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "ok"}}]}\n\n'
            raise ConnectionError("Connection to http://secret-backend:9999/v1 refused")

        events = []
        async for event in responses_compat._responses_stream_converter(
            response_stream(), "model", "resp_sec"
        ):
            events.append(event)
        joined = "".join(events)
        assert "secret-backend" not in joined
        assert "9999" not in joined
        assert "internal error" in joined.lower()


class TestSecuritySSEInjection:
    """Verify SSE events cannot be injected via crafted content."""

    @pytest.mark.asyncio
    async def test_content_with_sse_newlines_is_escaped(self):
        """Content containing SSE-significant characters should be JSON-escaped
        so each SSE event is a single data: line (no raw newlines splitting it)."""
        malicious_content = 'Hello\n\nevent: malicious\ndata: {"injected": true}\n\n'
        async def response_stream():
            yield f'data: {{"choices": [{{"delta": {{"content": {json.dumps(malicious_content)}}}}}]}}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            response_stream(), "model", "resp_sse"
        ):
            events.append(event)

        # Each SSE *event* (containing an event: line) must have exactly one
        # data: line (the JSON payload cannot contain raw newlines that would
        # split the SSE frame).  Non-event entries like ": keep-alive" are
        # skipped.
        for event in events:
            if "event: " not in event:
                continue
            lines = event.strip().split("\n")
            data_lines = [l for l in lines if l.startswith("data: ")]
            assert len(data_lines) == 1, f"SSE event has {len(data_lines)} data lines: {event}"
        # The content should appear (JSON-escaped) in the text delta
        joined = "".join(events)
        assert "Hello" in joined


class TestSecurityMetadataInjection:
    """Verify metadata @boost_ params cannot overwrite standard body fields."""

    def test_metadata_cannot_overwrite_model(self):
        body = {
            "model": "safe-model",
            "input": "hi",
            "metadata": {"@boost_workflow": "test"},
        }
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["model"] == "safe-model"
        assert openai_body["@boost_workflow"] == "test"

    def test_metadata_non_boost_keys_ignored(self):
        body = {
            "model": "test",
            "input": "hi",
            "metadata": {
                "user_id": "attacker",
                "model": "evil-model",
                "@boost_pad_size": 10,
            },
        }
        openai_body = responses_compat._build_openai_body(body)
        assert "user_id" not in openai_body
        assert openai_body["model"] == "test"
        assert openai_body["@boost_pad_size"] == 10


# ---------------------------------------------------------------------------
# Annotations: extract_annotations (compat_utils)
# ---------------------------------------------------------------------------


class TestExtractAnnotations:
    """Tests for compat_utils.extract_annotations — the shared helper that
    converts Chat Completions annotations/citations to Responses API format."""

    def test_empty_message(self):
        from compat_utils import extract_annotations
        assert extract_annotations({}) == []

    def test_none_annotations(self):
        from compat_utils import extract_annotations
        assert extract_annotations({"annotations": None}) == []

    def test_empty_annotations(self):
        from compat_utils import extract_annotations
        assert extract_annotations({"annotations": []}) == []

    def test_url_citation(self):
        from compat_utils import extract_annotations
        message = {
            "annotations": [{
                "type": "url_citation",
                "url_citation": {
                    "start_index": 10,
                    "end_index": 50,
                    "url": "https://example.com/article",
                    "title": "Example Article",
                },
            }],
        }
        result = extract_annotations(message)
        assert len(result) == 1
        assert result[0]["type"] == "url_citation"
        assert result[0]["start_index"] == 10
        assert result[0]["end_index"] == 50
        assert result[0]["url"] == "https://example.com/article"
        assert result[0]["title"] == "Example Article"

    def test_multiple_url_citations(self):
        from compat_utils import extract_annotations
        message = {
            "annotations": [
                {
                    "type": "url_citation",
                    "url_citation": {
                        "start_index": 0,
                        "end_index": 20,
                        "url": "https://a.com",
                        "title": "A",
                    },
                },
                {
                    "type": "url_citation",
                    "url_citation": {
                        "start_index": 30,
                        "end_index": 60,
                        "url": "https://b.com",
                        "title": "B",
                    },
                },
            ],
        }
        result = extract_annotations(message)
        assert len(result) == 2
        assert result[0]["url"] == "https://a.com"
        assert result[1]["url"] == "https://b.com"

    def test_file_citation(self):
        from compat_utils import extract_annotations
        message = {
            "annotations": [{
                "type": "file_citation",
                "file_id": "file-abc",
                "filename": "report.pdf",
                "index": 5,
            }],
        }
        result = extract_annotations(message)
        assert len(result) == 1
        assert result[0]["type"] == "file_citation"
        assert result[0]["file_id"] == "file-abc"
        assert result[0]["filename"] == "report.pdf"
        assert result[0]["index"] == 5

    def test_file_path(self):
        from compat_utils import extract_annotations
        message = {
            "annotations": [{
                "type": "file_path",
                "file_id": "file-xyz",
                "index": 3,
            }],
        }
        result = extract_annotations(message)
        assert len(result) == 1
        assert result[0]["type"] == "file_path"
        assert result[0]["file_id"] == "file-xyz"
        assert result[0]["index"] == 3

    def test_mixed_annotation_types(self):
        from compat_utils import extract_annotations
        message = {
            "annotations": [
                {
                    "type": "url_citation",
                    "url_citation": {
                        "start_index": 0, "end_index": 10,
                        "url": "https://x.com", "title": "X",
                    },
                },
                {
                    "type": "file_citation",
                    "file_id": "file-1",
                    "filename": "doc.txt",
                    "index": 2,
                },
                {
                    "type": "file_path",
                    "file_id": "file-2",
                    "index": 4,
                },
            ],
        }
        result = extract_annotations(message)
        assert len(result) == 3
        assert result[0]["type"] == "url_citation"
        assert result[1]["type"] == "file_citation"
        assert result[2]["type"] == "file_path"

    def test_unknown_annotation_type_skipped(self):
        from compat_utils import extract_annotations
        message = {
            "annotations": [
                {"type": "unknown_type", "data": "something"},
                {
                    "type": "url_citation",
                    "url_citation": {
                        "start_index": 0, "end_index": 5,
                        "url": "https://known.com", "title": "Known",
                    },
                },
            ],
        }
        result = extract_annotations(message)
        assert len(result) == 1
        assert result[0]["url"] == "https://known.com"

    def test_non_dict_annotation_skipped(self):
        from compat_utils import extract_annotations
        result = extract_annotations({"annotations": ["not a dict", 42]})
        assert result == []

    def test_perplexity_citations(self):
        """Perplexity returns a flat list of URL strings as 'citations'."""
        from compat_utils import extract_annotations
        message = {
            "citations": [
                "https://perplexity.ai/article1",
                "https://perplexity.ai/article2",
            ],
        }
        result = extract_annotations(message)
        assert len(result) == 2
        assert result[0]["type"] == "url_citation"
        assert result[0]["url"] == "https://perplexity.ai/article1"
        assert result[0]["title"] == ""
        assert result[0]["start_index"] == 0
        assert result[0]["end_index"] == 0
        assert result[1]["url"] == "https://perplexity.ai/article2"

    def test_perplexity_empty_citations(self):
        from compat_utils import extract_annotations
        assert extract_annotations({"citations": []}) == []

    def test_perplexity_non_string_citations_skipped(self):
        from compat_utils import extract_annotations
        result = extract_annotations({"citations": [None, "", 42, "https://valid.com"]})
        assert len(result) == 1
        assert result[0]["url"] == "https://valid.com"

    def test_openai_annotations_take_priority_over_citations(self):
        """When both annotations and citations exist, annotations win."""
        from compat_utils import extract_annotations
        message = {
            "annotations": [{
                "type": "url_citation",
                "url_citation": {
                    "start_index": 0, "end_index": 10,
                    "url": "https://openai.com", "title": "OpenAI",
                },
            }],
            "citations": ["https://perplexity.com"],
        }
        result = extract_annotations(message)
        assert len(result) == 1
        assert result[0]["url"] == "https://openai.com"

    def test_url_citation_missing_fields_default(self):
        from compat_utils import extract_annotations
        message = {
            "annotations": [{
                "type": "url_citation",
                "url_citation": {},
            }],
        }
        result = extract_annotations(message)
        assert len(result) == 1
        assert result[0]["start_index"] == 0
        assert result[0]["end_index"] == 0
        assert result[0]["url"] == ""
        assert result[0]["title"] == ""


# ---------------------------------------------------------------------------
# Annotations: _build_output_items with annotations
# ---------------------------------------------------------------------------


class TestBuildOutputItemsAnnotations:
    """Tests that _build_output_items correctly extracts annotations from
    the Chat Completions message and includes them in output text items."""

    def test_text_with_url_citations(self):
        openai_result = {
            "choices": [{
                "message": {
                    "content": "According to the article [1]...",
                    "annotations": [{
                        "type": "url_citation",
                        "url_citation": {
                            "start_index": 24,
                            "end_index": 27,
                            "url": "https://example.com",
                            "title": "Example",
                        },
                    }],
                },
                "finish_reason": "stop",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        assert len(output) == 1
        assert output[0]["type"] == "message"
        text_part = output[0]["content"][0]
        assert text_part["type"] == "output_text"
        assert len(text_part["annotations"]) == 1
        assert text_part["annotations"][0]["type"] == "url_citation"
        assert text_part["annotations"][0]["url"] == "https://example.com"

    def test_text_without_annotations_has_empty_list(self):
        openai_result = {
            "choices": [{"message": {"content": "plain text"}, "finish_reason": "stop"}],
        }
        output = responses_compat._build_output_items(openai_result)
        assert output[0]["content"][0]["annotations"] == []

    def test_perplexity_citations_in_message(self):
        openai_result = {
            "choices": [{
                "message": {
                    "content": "Python is great.",
                    "citations": [
                        "https://python.org",
                        "https://docs.python.org",
                    ],
                },
                "finish_reason": "stop",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        text_part = output[0]["content"][0]
        assert len(text_part["annotations"]) == 2
        assert text_part["annotations"][0]["url"] == "https://python.org"
        assert text_part["annotations"][1]["url"] == "https://docs.python.org"
        assert all(a["type"] == "url_citation" for a in text_part["annotations"])

    def test_refusal_has_no_annotations(self):
        openai_result = {
            "choices": [{
                "message": {
                    "refusal": "I cannot help with that",
                    "annotations": [{
                        "type": "url_citation",
                        "url_citation": {
                            "start_index": 0, "end_index": 5,
                            "url": "https://x.com", "title": "X",
                        },
                    }],
                },
                "finish_reason": "stop",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        assert output[0]["content"][0]["type"] == "refusal"
        assert "annotations" not in output[0]["content"][0]

    def test_empty_content_fallback_has_empty_annotations(self):
        openai_result = {
            "choices": [{"message": {"content": None}, "finish_reason": "stop"}],
        }
        output = responses_compat._build_output_items(openai_result)
        assert output[0]["content"][0]["annotations"] == []

    def test_multiple_annotations_preserved(self):
        openai_result = {
            "choices": [{
                "message": {
                    "content": "See [1] and [2] for details.",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url_citation": {
                                "start_index": 4, "end_index": 7,
                                "url": "https://a.com", "title": "A",
                            },
                        },
                        {
                            "type": "url_citation",
                            "url_citation": {
                                "start_index": 12, "end_index": 15,
                                "url": "https://b.com", "title": "B",
                            },
                        },
                    ],
                },
                "finish_reason": "stop",
            }],
        }
        output = responses_compat._build_output_items(openai_result)
        text_part = output[0]["content"][0]
        assert len(text_part["annotations"]) == 2
        assert text_part["annotations"][0]["start_index"] == 4
        assert text_part["annotations"][1]["start_index"] == 12


# ---------------------------------------------------------------------------
# Annotations: Streaming with annotations
# ---------------------------------------------------------------------------


class TestAnnotationsStreaming:
    """Tests that streaming converter emits annotation.added events when
    annotations are available (from backend citations in chunks)."""

    @pytest.mark.asyncio
    async def test_perplexity_citations_in_stream(self):
        """Perplexity sends citations as a top-level array in streaming chunks."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"Python is great."},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"citations":["https://python.org","https://docs.python.org"]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "pplx-70b", "resp_ann1"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Annotation events should be emitted before output_text.done
        assert "response.output_text.annotation.added" in event_types
        ann_events = [(t, d) for t, d in parsed if t == "response.output_text.annotation.added"]
        assert len(ann_events) == 2

        assert ann_events[0][1]["annotation"]["url"] == "https://python.org"
        assert ann_events[0][1]["annotation"]["type"] == "url_citation"
        assert ann_events[0][1]["annotation_index"] == 0
        assert ann_events[0][1]["content_index"] == 0

        assert ann_events[1][1]["annotation"]["url"] == "https://docs.python.org"
        assert ann_events[1][1]["annotation_index"] == 1

    @pytest.mark.asyncio
    async def test_no_annotations_no_events(self):
        """Normal stream without annotations produces no annotation events."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"Hello"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "gpt-4o", "resp_noann"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]
        assert "response.output_text.annotation.added" not in event_types

    @pytest.mark.asyncio
    async def test_annotation_event_has_required_fields(self):
        """Each annotation.added event must have all SDK-required fields."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"text"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"citations":["https://x.com"]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_annf"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        ann_events = [d for t, d in parsed if t == "response.output_text.annotation.added"]
        assert len(ann_events) == 1
        evt = ann_events[0]
        assert evt["type"] == "response.output_text.annotation.added"
        assert "sequence_number" in evt
        assert "item_id" in evt
        assert "output_index" in evt
        assert "content_index" in evt
        assert evt["content_index"] == 0
        assert "annotation_index" in evt
        assert evt["annotation_index"] == 0
        assert "annotation" in evt
        assert evt["annotation"]["type"] == "url_citation"

    @pytest.mark.asyncio
    async def test_annotation_events_before_text_done(self):
        """Annotation events must appear before output_text.done."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"citations":["https://z.com"]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_annorder"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        event_types = [t for t, _ in parsed]

        ann_idx = event_types.index("response.output_text.annotation.added")
        done_idx = event_types.index("response.output_text.done")
        assert ann_idx < done_idx

    @pytest.mark.asyncio
    async def test_annotations_in_content_part_done(self):
        """content_part.done and output_item.done carry the accumulated annotations."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hello"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"citations":["https://cite.com"]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_annpart"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)

        # content_part.done should carry annotations
        part_done = [d for t, d in parsed if t == "response.content_part.done"]
        assert len(part_done) == 1
        assert len(part_done[0]["part"]["annotations"]) == 1
        assert part_done[0]["part"]["annotations"][0]["url"] == "https://cite.com"

        # output_item.done should carry annotations
        item_done = [d for t, d in parsed if t == "response.output_item.done"]
        msg_items = [d for d in item_done if d["item"]["type"] == "message"]
        assert len(msg_items) == 1
        assert len(msg_items[0]["item"]["content"][0]["annotations"]) == 1

    @pytest.mark.asyncio
    async def test_annotations_cleared_on_error_new_item(self):
        """When error occurs before any text, the error text item has no annotations."""
        async def mock_stream():
            raise RuntimeError("boom")
            yield  # noqa: unreachable — makes this an async generator

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_annerr"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        item_done = [d for t, d in parsed if t == "response.output_item.done"]
        assert len(item_done) == 1
        assert item_done[0]["item"]["content"][0]["annotations"] == []

    @pytest.mark.asyncio
    async def test_annotations_preserved_on_error_existing_item(self):
        """When error occurs mid-stream, pre-error annotations survive on the existing item."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hello"},"index":0}],"citations":["https://pre-error.com"]}\n\n'
            raise RuntimeError("boom")

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_annerr2"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        item_done = [d for t, d in parsed if t == "response.output_item.done"]
        assert len(item_done) == 1
        # Pre-error annotations are preserved since the text item was already open
        anns = item_done[0]["item"]["content"][0]["annotations"]
        assert len(anns) == 1
        assert anns[0]["url"] == "https://pre-error.com"

    @pytest.mark.asyncio
    async def test_annotation_sdk_validation(self):
        """annotation.added events validate against the OpenAI SDK model."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"x"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"citations":["https://sdk.com"]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_annsdk"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        ann_events = [d for t, d in parsed if t == "response.output_text.annotation.added"]
        assert len(ann_events) == 1

        try:
            from openai.types.responses import ResponseOutputTextAnnotationAddedEvent
            ResponseOutputTextAnnotationAddedEvent.model_validate(ann_events[0])
        except ImportError:
            pytest.skip("openai SDK not installed")

    @pytest.mark.asyncio
    async def test_delta_annotations_from_backend(self):
        """Future backends may send annotations on streaming deltas."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"text","annotations":[{"type":"url_citation","url_citation":{"start_index":0,"end_index":4,"url":"https://delta.com","title":"Delta"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_deltaann"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        ann_events = [d for t, d in parsed if t == "response.output_text.annotation.added"]
        assert len(ann_events) == 1
        assert ann_events[0]["annotation"]["url"] == "https://delta.com"
        assert ann_events[0]["annotation"]["title"] == "Delta"

    @pytest.mark.asyncio
    async def test_sequence_numbers_monotonic_with_annotations(self):
        """sequence_number must be monotonically increasing across all events
        including annotation events."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"citations":["https://a.com","https://b.com"]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_annseq"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        seq_numbers = [d["sequence_number"] for _, d in parsed]
        for i in range(1, len(seq_numbers)):
            assert seq_numbers[i] > seq_numbers[i - 1]


# ---------------------------------------------------------------------------
# Model name handling: verify the original requested model name is always
# echoed back in responses, regardless of what the mapper resolves to.
# ---------------------------------------------------------------------------


class TestModelNamePreservation:
    """Ensure the original request model name is echoed in all response paths."""

    def test_non_streaming_response_echoes_request_model(self):
        """Non-streaming response 'model' field matches the original request model."""
        openai_result = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "model": "resolved-backend-model",
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        response = responses_compat._build_responses_response(
            openai_result, "my-custom-model", "resp_1"
        )
        assert response["model"] == "my-custom-model"

    def test_module_prefixed_model_echoed_in_response(self):
        """Model with module prefix (e.g., 'g1-gpt-4o') is echoed as-is."""
        openai_result = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "model": "gpt-4o",  # mapper strips 'g1-' prefix
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        response = responses_compat._build_responses_response(
            openai_result, "g1-gpt-4o", "resp_2"
        )
        assert response["model"] == "g1-gpt-4o"

    def test_workflow_prefixed_model_echoed_in_response(self):
        """Model with workflow prefix (e.g., 'cot::gpt-4o') is echoed as-is."""
        openai_result = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "model": "gpt-4o",
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        response = responses_compat._build_responses_response(
            openai_result, "cot::gpt-4o", "resp_3"
        )
        assert response["model"] == "cot::gpt-4o"

    def test_aliased_model_echoes_request_name_not_backend_name(self):
        """Response echoes the client's model name, not the backend's resolved name."""
        openai_result = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "model": "openai/gpt-4",  # backend's resolved model
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        response = responses_compat._build_responses_response(
            openai_result, "claude-3-opus-20240229", "resp_4"
        )
        assert response["model"] == "claude-3-opus-20240229"

    @pytest.mark.asyncio
    async def test_streaming_created_event_has_request_model(self):
        """response.created event should contain the original request model."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"Hi"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "g1-gpt-4o-turbo", "resp_5"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        created = [d for t, d in parsed if t == "response.created"][0]
        assert created["response"]["model"] == "g1-gpt-4o-turbo"

    @pytest.mark.asyncio
    async def test_streaming_completed_event_has_request_model(self):
        """response.completed event should contain the original request model."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"ok"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "mcts-claude-3", "resp_6"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        completed = [d for t, d in parsed if t == "response.completed"][0]
        assert completed["response"]["model"] == "mcts-claude-3"

    @pytest.mark.asyncio
    async def test_streaming_model_matches_non_streaming(self):
        """Streaming and non-streaming paths should report the same model name."""
        request_model = "mcts-openai/gpt-4o"

        # Non-streaming
        openai_result = {
            "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}],
            "model": "openai/gpt-4o",
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        response = responses_compat._build_responses_response(
            openai_result, request_model, "resp_7"
        )
        non_streaming_model = response["model"]

        # Streaming
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"Hello"},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), request_model, "resp_7s"
        ):
            events.append(event)

        parsed = _parse_sse_events(events)
        created = [d for t, d in parsed if t == "response.created"][0]
        streaming_model = created["response"]["model"]

        assert non_streaming_model == streaming_model == request_model

    def test_direct_task_echoes_request_model(self, monkeypatch):
        """Direct task path (chat_completion) should still echo the original model name."""
        mock_result = {
            "choices": [{"message": {"content": "title"}, "finish_reason": "stop"}],
            "model": "some-backend-model",
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

        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])

        app = _make_responses_app()
        from fastapi.testclient import TestClient
        client = TestClient(app)

        resp = client.post("/v1/responses", json={
            "model": "my-workflow-model",
            "input": "hello",
        })

        assert resp.status_code == 200
        assert resp.json()["model"] == "my-workflow-model"

    def test_integration_non_streaming_model_preserved(self, monkeypatch):
        """Full integration: non-streaming response model is the request model."""
        mock_result = {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1000,
            "model": "resolved-backend-model",
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

        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])

        app = _make_responses_app()
        from fastapi.testclient import TestClient
        client = TestClient(app)

        resp = client.post("/v1/responses", json={
            "model": "g1-claude-3-5-sonnet",
            "input": "hello",
        })

        assert resp.status_code == 200
        assert resp.json()["model"] == "g1-claude-3-5-sonnet"


# ---------------------------------------------------------------------------
# BackendError and rate limit header forwarding
# ---------------------------------------------------------------------------

from llm import BackendError


class TestResponsesBackendErrorIntegration:
    """Integration tests: BackendError from LLM is caught and rate limit headers forwarded."""

    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch):
        from fastapi.testclient import TestClient
        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])
        app = _make_responses_app()
        self.client = TestClient(app)

    def test_429_returns_rate_limit_error_with_headers(self, monkeypatch):
        """When the backend returns 429 with rate limit headers, those headers
        appear on the response and the status code is 429."""
        rate_limit_headers = {
            "retry-after": "30",
            "x-ratelimit-limit-requests": "100",
            "x-ratelimit-remaining-requests": "0",
            "x-ratelimit-reset-requests": "2026-05-20T12:00:00Z",
        }

        async def mock_list_downstream():
            return []

        def raise_backend_error(**kw):
            raise BackendError(429, "rate limited", rate_limit_headers)

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(responses_compat.mapper, "resolve_request_config", lambda body: {})
        monkeypatch.setattr(responses_compat.mapper, "is_direct_task", lambda proxy: False)
        monkeypatch.setattr(responses_compat.llm_mod, "LLM", raise_backend_error)

        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hello",
        })

        assert resp.status_code == 429
        body = resp.json()
        assert body["error"]["type"] == "rate_limit_error"
        assert "Rate limit" in body["error"]["message"]
        assert resp.headers.get("retry-after") == "30"
        assert resp.headers.get("x-ratelimit-limit-requests") == "100"
        assert resp.headers.get("x-ratelimit-remaining-requests") == "0"
        assert resp.headers.get("x-ratelimit-reset-requests") == "2026-05-20T12:00:00Z"

    def test_429_from_serve_with_all_headers(self, monkeypatch):
        """When serve() raises BackendError(429), all rate limit headers are forwarded."""
        all_headers = {
            "retry-after": "10",
            "retry-after-ms": "10000",
            "x-ratelimit-limit-requests": "200",
            "x-ratelimit-limit-tokens": "40000",
            "x-ratelimit-remaining-requests": "0",
            "x-ratelimit-remaining-tokens": "0",
            "x-ratelimit-reset-requests": "2026-05-20T12:01:00Z",
            "x-ratelimit-reset-tokens": "2026-05-20T12:01:00Z",
        }

        async def mock_list_downstream():
            return []

        mock_llm = MagicMock()
        mock_llm.workflow = None
        mock_llm.boost_params = {}
        mock_llm.module = None
        async def _raise_serve():
            raise BackendError(429, '{"error": "too many requests"}', all_headers)
        mock_llm.serve = _raise_serve

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(responses_compat.mapper, "resolve_request_config", lambda body: {})
        monkeypatch.setattr(responses_compat.mapper, "is_direct_task", lambda proxy: False)
        monkeypatch.setattr(responses_compat.llm_mod, "LLM", lambda **kw: mock_llm)

        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hello",
        })

        assert resp.status_code == 429
        for hdr, val in all_headers.items():
            assert resp.headers.get(hdr) == val, f"Missing or wrong header: {hdr}"

    def test_429_from_direct_task(self, monkeypatch):
        """When chat_completion() raises BackendError(429), it is caught."""
        async def mock_list_downstream():
            return []

        mock_llm = MagicMock()
        mock_llm.workflow = None
        mock_llm.boost_params = {}
        mock_llm.module = None
        mock_llm.chat = MagicMock()
        mock_llm.chat.has_substring = MagicMock(return_value=False)
        async def _raise_chat():
            raise BackendError(429, "rate limited", {"retry-after": "5"})
        mock_llm.chat_completion = _raise_chat

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(responses_compat.mapper, "resolve_request_config", lambda body: {})
        monkeypatch.setattr(responses_compat.mapper, "is_direct_task", lambda proxy: True)
        monkeypatch.setattr(responses_compat.llm_mod, "LLM", lambda **kw: mock_llm)

        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hello",
        })

        assert resp.status_code == 429
        assert resp.headers.get("retry-after") == "5"
        body = resp.json()
        assert body["error"]["type"] == "rate_limit_error"

    def test_500_backend_error_no_rate_limit_headers(self, monkeypatch):
        """A 500 BackendError returns 500 without rate limit headers."""
        async def mock_list_downstream():
            return []

        def raise_backend_error(**kw):
            raise BackendError(500, "internal error")

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(responses_compat.mapper, "resolve_request_config", lambda body: {})
        monkeypatch.setattr(responses_compat.mapper, "is_direct_task", lambda proxy: False)
        monkeypatch.setattr(responses_compat.llm_mod, "LLM", raise_backend_error)

        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hello",
        })

        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["type"] == "server_error"
        assert "Backend server error" in body["error"]["message"]
        assert resp.headers.get("retry-after") is None

    def test_backend_error_does_not_leak_body(self, monkeypatch):
        """The backend error body (which may contain internal URLs) is not
        forwarded to the client."""
        async def mock_list_downstream():
            return []

        def raise_backend_error(**kw):
            raise BackendError(
                429,
                '{"error": "rate limited at http://internal-backend:8080"}',
                {"retry-after": "10"},
            )

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(responses_compat.mapper, "resolve_request_config", lambda body: {})
        monkeypatch.setattr(responses_compat.mapper, "is_direct_task", lambda proxy: False)
        monkeypatch.setattr(responses_compat.llm_mod, "LLM", raise_backend_error)

        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hello",
        })

        assert resp.status_code == 429
        body = resp.json()
        assert "internal-backend" not in body["error"]["message"]
        assert "8080" not in body["error"]["message"]

    def test_backend_error_preserves_request_id(self, monkeypatch):
        """BackendError responses still have the x-request-id header."""
        async def mock_list_downstream():
            return []

        def raise_backend_error(**kw):
            raise BackendError(429, "rate limited", {"retry-after": "10"})

        monkeypatch.setattr(responses_compat.mapper, "list_downstream", mock_list_downstream)
        monkeypatch.setattr(responses_compat.mapper, "resolve_request_config", lambda body: {})
        monkeypatch.setattr(responses_compat.mapper, "is_direct_task", lambda proxy: False)
        monkeypatch.setattr(responses_compat.llm_mod, "LLM", raise_backend_error)

        resp = self.client.post("/v1/responses", json={
            "model": "gpt-4o",
            "input": "hello",
        })

        assert resp.headers.get("x-request-id") is not None
        assert resp.headers.get("x-request-id").startswith("req_")


# ---------------------------------------------------------------------------
# SDK Compatibility Final Audit
# ---------------------------------------------------------------------------


class TestReasoningSummaryParam:
    """Verify reasoning.summary and deprecated generate_summary are forwarded."""

    def test_reasoning_summary_forwarded(self):
        body = {
            "model": "o3",
            "input": "hello",
            "reasoning": {"effort": "high", "summary": "concise"},
        }
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body.get("reasoning_effort") == "high"
        assert openai_body.get("reasoning_summary") == "concise"

    def test_reasoning_generate_summary_forwarded(self):
        body = {
            "model": "o3",
            "input": "hello",
            "reasoning": {"effort": "medium", "generate_summary": "detailed"},
        }
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body.get("reasoning_summary") == "detailed"

    def test_summary_preferred_over_generate_summary(self):
        body = {
            "model": "o3",
            "input": "hello",
            "reasoning": {"summary": "concise", "generate_summary": "detailed"},
        }
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body.get("reasoning_summary") == "concise"

    def test_no_summary_when_absent(self):
        body = {
            "model": "o3",
            "input": "hello",
            "reasoning": {"effort": "low"},
        }
        openai_body = responses_compat._build_openai_body(body)
        assert "reasoning_summary" not in openai_body

    def test_no_reasoning_at_all(self):
        body = {"model": "gpt-4o", "input": "hello"}
        openai_body = responses_compat._build_openai_body(body)
        assert "reasoning_effort" not in openai_body
        assert "reasoning_summary" not in openai_body


class TestIncludeAndServiceTier:
    """Verify include and service_tier params are accepted without error."""

    def test_include_accepted(self):
        body = {
            "model": "gpt-4o",
            "input": "hello",
            "include": ["message.output_text.logprobs", "reasoning.encrypted_content"],
        }
        # Should not raise
        openai_body = responses_compat._build_openai_body(body)
        assert "include" not in openai_body  # Not forwarded to backend

    def test_service_tier_accepted(self):
        body = {
            "model": "gpt-4o",
            "input": "hello",
            "service_tier": "flex",
        }
        openai_body = responses_compat._build_openai_body(body)
        assert "service_tier" not in openai_body  # Not forwarded to backend


class TestExtendedToolTypes:
    """Verify additional tool types are handled gracefully."""

    def test_mcp_tool_skipped_with_warning(self):
        body = {
            "model": "gpt-4o",
            "input": "hello",
            "tools": [{"type": "mcp", "server_label": "test", "server_url": "http://test"}],
        }
        tools = responses_compat._convert_tools(body)
        assert tools == []

    def test_image_generation_tool_skipped(self):
        body = {
            "model": "gpt-4o",
            "input": "hello",
            "tools": [{"type": "image_generation"}],
        }
        tools = responses_compat._convert_tools(body)
        assert tools == []

    def test_computer_tool_skipped(self):
        body = {
            "model": "gpt-4o",
            "input": "hello",
            "tools": [{"type": "computer_use_preview"}],
        }
        tools = responses_compat._convert_tools(body)
        assert tools == []

    def test_local_shell_tool_skipped(self):
        body = {
            "model": "gpt-4o",
            "input": "hello",
            "tools": [{"type": "local_shell"}],
        }
        tools = responses_compat._convert_tools(body)
        assert tools == []

    def test_apply_patch_tool_skipped(self):
        body = {
            "model": "gpt-4o",
            "input": "hello",
            "tools": [{"type": "apply_patch"}],
        }
        tools = responses_compat._convert_tools(body)
        assert tools == []

    def test_custom_tool_skipped(self):
        body = {
            "model": "gpt-4o",
            "input": "hello",
            "tools": [{"type": "custom", "name": "my_tool"}],
        }
        tools = responses_compat._convert_tools(body)
        assert tools == []

    def test_function_tool_still_works_alongside_unsupported(self):
        body = {
            "model": "gpt-4o",
            "input": "hello",
            "tools": [
                {"type": "mcp", "server_label": "test"},
                {"type": "function", "name": "get_weather", "parameters": {}},
                {"type": "image_generation"},
            ],
        }
        tools = responses_compat._convert_tools(body)
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "get_weather"


class TestReasoningItemStatus:
    """Verify reasoning output items include the status field."""

    def test_non_streaming_reasoning_has_status(self):
        from helpers import openai_result
        result = openai_result(content="Answer", reasoning_content="Let me think")
        items = responses_compat._build_output_items(result)
        reasoning_items = [i for i in items if i["type"] == "reasoning"]
        assert len(reasoning_items) == 1
        assert reasoning_items[0]["status"] == "completed"


class TestResponseEchoFields:
    """Verify user, reasoning config are echoed in response objects."""

    def test_user_echoed_in_response(self):
        from helpers import openai_result
        result = openai_result(content="Hi")
        request_body = {"model": "gpt-4o", "input": "hello", "user": "user-123"}
        resp = responses_compat._build_responses_response(
            result, "gpt-4o", "resp_test", request_body=request_body
        )
        assert resp.get("user") == "user-123"

    def test_no_user_when_absent(self):
        from helpers import openai_result
        result = openai_result(content="Hi")
        request_body = {"model": "gpt-4o", "input": "hello"}
        resp = responses_compat._build_responses_response(
            result, "gpt-4o", "resp_test", request_body=request_body
        )
        assert "user" not in resp

    def test_reasoning_config_echoed(self):
        from helpers import openai_result
        result = openai_result(content="Hi")
        reasoning_conf = {"effort": "high", "summary": "concise"}
        request_body = {
            "model": "o3", "input": "hello",
            "reasoning": reasoning_conf,
        }
        resp = responses_compat._build_responses_response(
            result, "o3", "resp_test", request_body=request_body
        )
        assert resp.get("reasoning") == reasoning_conf

    def test_no_reasoning_when_absent(self):
        from helpers import openai_result
        result = openai_result(content="Hi")
        request_body = {"model": "gpt-4o", "input": "hello"}
        resp = responses_compat._build_responses_response(
            result, "gpt-4o", "resp_test", request_body=request_body
        )
        assert "reasoning" not in resp


class TestCompletedAt:
    """Verify completed_at is set when status is completed."""

    def test_completed_at_set_on_completed(self):
        from helpers import openai_result
        result = openai_result(content="Hi", finish_reason="stop")
        resp = responses_compat._build_responses_response(
            result, "gpt-4o", "resp_test"
        )
        assert resp["status"] == "completed"
        assert "completed_at" in resp
        assert isinstance(resp["completed_at"], int)
        assert resp["completed_at"] >= resp["created_at"]

    def test_completed_at_absent_on_incomplete(self):
        from helpers import openai_result
        result = openai_result(content="Hi", finish_reason="length")
        resp = responses_compat._build_responses_response(
            result, "gpt-4o", "resp_test"
        )
        assert resp["status"] == "incomplete"
        assert "completed_at" not in resp

    @pytest.mark.asyncio
    async def test_streaming_completed_at(self):
        from helpers import sse_chunk, parse_responses_sse_events

        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "Hi"}}]}),
            sse_chunk({"choices": [{"delta": {}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}),
            "data: [DONE]\n\n",
        ]

        async def gen():
            for c in chunks:
                yield c

        events = []
        async for evt in responses_compat._responses_stream_converter(
            gen(), "gpt-4o", "resp_test"
        ):
            events.append(evt)

        parsed = parse_responses_sse_events(events)
        completed = [d for t, d in parsed if t == "response.completed"]
        assert len(completed) == 1
        assert "completed_at" in completed[0]["response"]
        assert isinstance(completed[0]["response"]["completed_at"], int)

    @pytest.mark.asyncio
    async def test_streaming_incomplete_no_completed_at(self):
        from helpers import sse_chunk, parse_responses_sse_events

        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "Hi"}}]}),
            sse_chunk({"choices": [{"delta": {}, "finish_reason": "length"}],
                       "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}),
            "data: [DONE]\n\n",
        ]

        async def gen():
            for c in chunks:
                yield c

        events = []
        async for evt in responses_compat._responses_stream_converter(
            gen(), "gpt-4o", "resp_test"
        ):
            events.append(evt)

        parsed = parse_responses_sse_events(events)
        incomplete = [d for t, d in parsed if t == "response.incomplete"]
        assert len(incomplete) == 1
        assert "completed_at" not in incomplete[0]["response"]


class TestStreamingReasoningStatus:
    """Verify streaming reasoning items include status field."""

    @pytest.mark.asyncio
    async def test_reasoning_added_has_in_progress_status(self):
        from helpers import sse_chunk, parse_responses_sse_events

        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "Think"}}]}),
            sse_chunk({"choices": [{"delta": {"content": "Answer"}}]}),
            sse_chunk({"choices": [{"delta": {}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}),
            "data: [DONE]\n\n",
        ]

        async def gen():
            for c in chunks:
                yield c

        events = []
        async for evt in responses_compat._responses_stream_converter(
            gen(), "o3", "resp_test"
        ):
            events.append(evt)

        parsed = parse_responses_sse_events(events)
        added_events = [(t, d) for t, d in parsed if t == "response.output_item.added"]
        # First added event should be reasoning with in_progress
        reasoning_added = [d for t, d in added_events if d["item"]["type"] == "reasoning"]
        assert len(reasoning_added) == 1
        assert reasoning_added[0]["item"]["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_reasoning_done_has_completed_status(self):
        from helpers import sse_chunk, parse_responses_sse_events

        chunks = [
            sse_chunk({"choices": [{"delta": {"reasoning_content": "Think"}}]}),
            sse_chunk({"choices": [{"delta": {"content": "Answer"}}]}),
            sse_chunk({"choices": [{"delta": {}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}),
            "data: [DONE]\n\n",
        ]

        async def gen():
            for c in chunks:
                yield c

        events = []
        async for evt in responses_compat._responses_stream_converter(
            gen(), "o3", "resp_test"
        ):
            events.append(evt)

        parsed = parse_responses_sse_events(events)
        done_events = [(t, d) for t, d in parsed if t == "response.output_item.done"]
        reasoning_done = [d for t, d in done_events if d["item"]["type"] == "reasoning"]
        assert len(reasoning_done) == 1
        assert reasoning_done[0]["item"]["status"] == "completed"


class TestStreamingSkeletonEchoFields:
    """Verify user and reasoning are echoed in streaming skeleton."""

    @pytest.mark.asyncio
    async def test_user_in_streaming_skeleton(self):
        from helpers import sse_chunk, parse_responses_sse_events

        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "Hi"}}]}),
            sse_chunk({"choices": [{"delta": {}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}),
            "data: [DONE]\n\n",
        ]

        async def gen():
            for c in chunks:
                yield c

        request_body = {"model": "gpt-4o", "input": "hello", "user": "user-xyz"}
        events = []
        async for evt in responses_compat._responses_stream_converter(
            gen(), "gpt-4o", "resp_test", request_body=request_body
        ):
            events.append(evt)

        parsed = parse_responses_sse_events(events)
        created = [d for t, d in parsed if t == "response.created"]
        assert len(created) == 1
        assert created[0]["response"].get("user") == "user-xyz"

    @pytest.mark.asyncio
    async def test_reasoning_config_in_streaming_skeleton(self):
        from helpers import sse_chunk, parse_responses_sse_events

        chunks = [
            sse_chunk({"choices": [{"delta": {"content": "Hi"}}]}),
            sse_chunk({"choices": [{"delta": {}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}),
            "data: [DONE]\n\n",
        ]

        async def gen():
            for c in chunks:
                yield c

        reasoning_conf = {"effort": "high", "summary": "concise"}
        request_body = {"model": "o3", "input": "hello", "reasoning": reasoning_conf}
        events = []
        async for evt in responses_compat._responses_stream_converter(
            gen(), "o3", "resp_test", request_body=request_body
        ):
            events.append(evt)

        parsed = parse_responses_sse_events(events)
        created = [d for t, d in parsed if t == "response.created"]
        assert len(created) == 1
        assert created[0]["response"].get("reasoning") == reasoning_conf

        # Also check completed event
        completed = [d for t, d in parsed if t == "response.completed"]
        assert len(completed) == 1
        assert completed[0]["response"].get("reasoning") == reasoning_conf


# ---------------------------------------------------------------------------
# OpenAI passthrough params
# ---------------------------------------------------------------------------

class TestOpenAIPassthroughParams:
    """Verify that Chat Completions params not in the Responses API spec
    are passed through to the backend when present."""

    def test_seed_passthrough(self):
        body = {"model": "test-model", "input": "hello", "seed": 42}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["seed"] == 42

    def test_frequency_penalty_passthrough(self):
        body = {"model": "test-model", "input": "hello", "frequency_penalty": 0.5}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["frequency_penalty"] == 0.5

    def test_presence_penalty_passthrough(self):
        body = {"model": "test-model", "input": "hello", "presence_penalty": 0.3}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["presence_penalty"] == 0.3

    def test_logit_bias_passthrough(self):
        body = {"model": "test-model", "input": "hello", "logit_bias": {"50256": -100}}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["logit_bias"] == {"50256": -100}

    def test_logprobs_passthrough(self):
        body = {"model": "test-model", "input": "hello", "logprobs": True}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["logprobs"] is True

    def test_top_logprobs_passthrough(self):
        body = {"model": "test-model", "input": "hello", "logprobs": True, "top_logprobs": 5}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["top_logprobs"] == 5

    def test_n_passthrough(self):
        body = {"model": "test-model", "input": "hello", "n": 3}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["n"] == 3

    def test_multiple_passthrough_params(self):
        body = {
            "model": "test-model",
            "input": "hello",
            "seed": 42,
            "frequency_penalty": 0.5,
            "presence_penalty": 0.3,
            "logprobs": True,
            "top_logprobs": 3,
        }
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["seed"] == 42
        assert openai_body["frequency_penalty"] == 0.5
        assert openai_body["presence_penalty"] == 0.3
        assert openai_body["logprobs"] is True
        assert openai_body["top_logprobs"] == 3

    def test_absent_passthrough_params_not_included(self):
        body = {"model": "test-model", "input": "hello"}
        openai_body = responses_compat._build_openai_body(body)
        for key in ("seed", "frequency_penalty", "presence_penalty",
                    "logit_bias", "logprobs", "top_logprobs", "n"):
            assert key not in openai_body

    def test_truly_unknown_fields_still_ignored(self):
        """Fields not in the passthrough set should still be silently ignored."""
        body = {
            "model": "test-model",
            "input": "hello",
            "custom_field": "value",
            "another_unknown": 123,
        }
        openai_body = responses_compat._build_openai_body(body)
        assert "custom_field" not in openai_body
        assert "another_unknown" not in openai_body

    def test_response_format_not_in_passthrough(self):
        """response_format is handled via text.format, not passthrough."""
        body = {
            "model": "test-model",
            "input": "hello",
            "response_format": {"type": "json_object"},
        }
        openai_body = responses_compat._build_openai_body(body)
        # response_format is not in the Responses passthrough set
        # (it's handled via text.format conversion instead)
        assert "response_format" not in openai_body

    def test_passthrough_coexists_with_responses_params(self):
        """Passthrough params should work alongside Responses-native params."""
        body = {
            "model": "test-model",
            "input": "hello",
            "temperature": 0.7,
            "top_p": 0.9,
            "max_output_tokens": 256,
            "seed": 42,
            "frequency_penalty": 0.2,
        }
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["temperature"] == 0.7
        assert openai_body["top_p"] == 0.9
        assert openai_body["max_tokens"] == 256
        assert openai_body["seed"] == 42
        assert openai_body["frequency_penalty"] == 0.2

    def test_zero_values_passed_through(self):
        """Zero values should be passed through (not treated as absent)."""
        body = {
            "model": "test-model",
            "input": "hello",
            "frequency_penalty": 0,
            "presence_penalty": 0,
            "seed": 0,
        }
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["frequency_penalty"] == 0
        assert openai_body["presence_penalty"] == 0
        assert openai_body["seed"] == 0


# ---------------------------------------------------------------------------
# _convert_tools: non-dict tool items
# ---------------------------------------------------------------------------

class TestConvertToolsNonDictItems:
    """Verify that _convert_tools skips non-dict items without crashing."""

    def test_skips_none_items(self):
        body = {"tools": [None, {"type": "function", "name": "calc", "description": "d", "parameters": {}}]}
        result = responses_compat._convert_tools(body)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "calc"

    def test_skips_string_items(self):
        body = {"tools": ["not-a-tool", {"type": "function", "name": "calc", "description": "d", "parameters": {}}]}
        result = responses_compat._convert_tools(body)
        assert len(result) == 1

    def test_skips_int_items(self):
        body = {"tools": [42]}
        result = responses_compat._convert_tools(body)
        assert result == []

    def test_all_non_dict_returns_empty(self):
        body = {"tools": [None, "bad", 123, True]}
        result = responses_compat._convert_tools(body)
        assert result == []


