"""Tests for Boost's Anthropic-compatible Messages API translation layer."""

import json
import unittest
from unittest.mock import patch, MagicMock

import pytest

# Module stubs for mapper/llm are registered in conftest.py

import anthropic_compat


def make_request(headers=None):
    """Build a fake Starlette Request with the given headers."""
    from fastapi import Request

    raw_headers = [(b"content-type", b"application/json")]

    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), value.encode()))

    return Request(
        scope={
            "type": "http",
            "query_string": b"",
            "headers": raw_headers,
        }
    )


# ---------------------------------------------------------------------------
# Auth: _synthesize_authorization
# ---------------------------------------------------------------------------

class TestSynthesizeAuthorization:
    def test_uses_x_api_key_when_authorization_is_missing(self):
        request = make_request({"x-api-key": "sk-anthropic"})
        anthropic_compat._synthesize_authorization(request)

        assert request.headers["authorization"] == "Bearer sk-anthropic"

    def test_preserves_explicit_authorization_header(self):
        request = make_request({
            "authorization": "Bearer explicit-token",
            "x-api-key": "sk-anthropic",
        })
        anthropic_compat._synthesize_authorization(request)

        assert request.headers["authorization"] == "Bearer explicit-token"
        auth_headers = [
            h for h in request.scope["headers"]
            if h[0] == b"authorization"
        ]
        assert len(auth_headers) == 1
        assert auth_headers[0] == (b"authorization", b"Bearer explicit-token")


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------

class TestValidateRequest:
    def test_missing_model(self):
        resp = anthropic_compat._validate_request({"max_tokens": 64, "messages": [{"role": "user", "content": "hi"}]})
        assert resp is not None
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "invalid_request_error"
        assert "model" in body["error"]["message"]

    def test_missing_max_tokens(self):
        resp = anthropic_compat._validate_request({"model": "m", "messages": [{"role": "user", "content": "hi"}]})
        assert resp is not None
        body = json.loads(resp.body.decode())
        assert "max_tokens" in body["error"]["message"]

    def test_empty_messages(self):
        resp = anthropic_compat._validate_request({"model": "m", "max_tokens": 64, "messages": []})
        assert resp is not None

    def test_system_role_rejected(self):
        resp = anthropic_compat._validate_request({
            "model": "m",
            "max_tokens": 64,
            "messages": [{"role": "system", "content": "you are helpful"}],
        })
        assert resp is not None
        body = json.loads(resp.body.decode())
        assert "system" in body["error"]["message"].lower()

    def test_valid_request(self):
        resp = anthropic_compat._validate_request({
            "model": "m",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp is None


# ---------------------------------------------------------------------------
# Message conversion: _convert_messages
# ---------------------------------------------------------------------------

class TestConvertMessages:
    def test_system_string(self):
        body = {
            "system": "You are helpful.",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert msgs[0] == {"role": "system", "content": "You are helpful."}
        assert msgs[1] == {"role": "user", "content": "Hello"}

    def test_system_list_of_text_blocks(self):
        body = {
            "system": [
                {"type": "text", "text": "Part one."},
                {"type": "text", "text": "Part two."},
            ],
            "messages": [{"role": "user", "content": "Hello"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert msgs[0] == {"role": "system", "content": "Part one.\nPart two."}

    def test_user_string_message(self):
        body = {"messages": [{"role": "user", "content": "Just text"}]}
        msgs = anthropic_compat._convert_messages(body)
        assert msgs == [{"role": "user", "content": "Just text"}]

    def test_user_message_with_image(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this."},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": "abc123",
                            },
                        },
                    ],
                }
            ],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        content_parts = msgs[0]["content"]
        assert isinstance(content_parts, list)
        assert content_parts[0] == {"type": "text", "text": "Describe this."}
        assert content_parts[1]["type"] == "image_url"
        assert content_parts[1]["image_url"]["url"] == "data:image/jpeg;base64,abc123"

    def test_user_message_with_tool_result(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": [{"type": "text", "text": "tool output"}],
                        },
                    ],
                }
            ],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert msgs[0] == {
            "role": "tool",
            "tool_call_id": "toolu_1",
            "content": "tool output",
        }

    def test_user_message_with_tool_result_string_content(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_2",
                            "content": "plain string result",
                        },
                    ],
                }
            ],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert msgs[0]["content"] == "plain string result"

    def test_assistant_string_message(self):
        body = {"messages": [{"role": "assistant", "content": "I will help."}]}
        msgs = anthropic_compat._convert_messages(body)
        assert msgs == [{"role": "assistant", "content": "I will help."}]

    def test_assistant_message_with_tool_use(self):
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Let me check."},
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "search",
                            "input": {"query": "weather"},
                        },
                    ],
                }
            ],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["content"] == "Let me check."
        assert msgs[0]["tool_calls"] == [
            {
                "id": "toolu_1",
                "type": "function",
                "function": {
                    "name": "search",
                    "arguments": '{"query": "weather"}',
                },
            }
        ]

    def test_assistant_message_with_only_tool_use(self):
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "search",
                            "input": {"query": "weather"},
                        },
                    ],
                }
            ],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert msgs[0]["content"] is None
        assert len(msgs[0]["tool_calls"]) == 1


# ---------------------------------------------------------------------------
# _build_openai_body — full pipeline
# ---------------------------------------------------------------------------

class TestBuildOpenaiBody:
    def test_tool_use_and_tool_result_round_trip(self):
        body = {
            "model": "claude-test",
            "max_tokens": 64,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Checking."},
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "memory_recall",
                            "input": {},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": [{"type": "text", "text": "memory result"}],
                        },
                    ],
                },
            ],
        }

        openai_body = anthropic_compat._build_openai_body(body)

        assert openai_body["messages"][0]["role"] == "assistant"
        assert openai_body["messages"][0]["tool_calls"][0] == {
            "id": "toolu_1",
            "type": "function",
            "function": {
                "name": "memory_recall",
                "arguments": "{}",
            },
        }
        assert openai_body["messages"][1] == {
            "role": "tool",
            "tool_call_id": "toolu_1",
            "content": "memory result",
        }

    def test_includes_model_and_params(self):
        body = {
            "model": "claude-3",
            "max_tokens": 128,
            "temperature": 0.5,
            "messages": [{"role": "user", "content": "hi"}],
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert openai_body["model"] == "claude-3"
        assert openai_body["max_tokens"] == 128
        assert openai_body["temperature"] == 0.5

    def test_includes_tools_when_present(self):
        body = {
            "model": "claude-3",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "name": "search",
                    "description": "Search the web",
                    "input_schema": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                    },
                }
            ],
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert openai_body["tools"] == [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search the web",
                    "parameters": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                    },
                },
            }
        ]

    def test_no_tools_key_when_empty(self):
        body = {
            "model": "claude-3",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert "tools" not in openai_body


# ---------------------------------------------------------------------------
# Parameter conversion: _convert_params
# ---------------------------------------------------------------------------

class TestConvertParams:
    def test_basic_params(self):
        body = {"max_tokens": 256, "temperature": 0.7, "top_p": 0.9}
        params = anthropic_compat._convert_params(body)
        assert params == {"max_tokens": 256, "temperature": 0.7, "top_p": 0.9}

    def test_stop_sequences(self):
        body = {"stop_sequences": ["\n\nHuman:", "\n\nAssistant:"]}
        params = anthropic_compat._convert_params(body)
        assert params["stop"] == ["\n\nHuman:", "\n\nAssistant:"]
        assert "stop_sequences" not in params

    def test_stream(self):
        body = {"stream": True}
        params = anthropic_compat._convert_params(body)
        assert params["stream"] is True
        assert params["stream_options"] == {"include_usage": True}

    def test_empty_body(self):
        params = anthropic_compat._convert_params({})
        assert params == {}


# ---------------------------------------------------------------------------
# Tool conversion: _convert_tools, _convert_tool_choice
# ---------------------------------------------------------------------------

class TestConvertTools:
    def test_converts_anthropic_tools_to_openai(self):
        body = {
            "tools": [
                {
                    "name": "calculator",
                    "description": "Do math",
                    "input_schema": {
                        "type": "object",
                        "properties": {"expr": {"type": "string"}},
                    },
                },
            ],
        }
        result = anthropic_compat._convert_tools(body)
        assert result == [
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "Do math",
                    "parameters": {
                        "type": "object",
                        "properties": {"expr": {"type": "string"}},
                    },
                },
            },
        ]

    def test_no_tools(self):
        assert anthropic_compat._convert_tools({}) == []
        assert anthropic_compat._convert_tools({"tools": None}) == []
        assert anthropic_compat._convert_tools({"tools": []}) == []


class TestConvertToolChoice:
    def test_auto(self):
        assert anthropic_compat._convert_tool_choice({"tool_choice": {"type": "auto"}}) == "auto"

    def test_any(self):
        assert anthropic_compat._convert_tool_choice({"tool_choice": {"type": "any"}}) == "required"

    def test_none(self):
        assert anthropic_compat._convert_tool_choice({"tool_choice": {"type": "none"}}) == "none"

    def test_specific_tool(self):
        result = anthropic_compat._convert_tool_choice({"tool_choice": {"type": "tool", "name": "search"}})
        assert result == {"type": "function", "function": {"name": "search"}}

    def test_absent(self):
        assert anthropic_compat._convert_tool_choice({}) is None

    def test_unknown_type(self):
        assert anthropic_compat._convert_tool_choice({"tool_choice": {"type": "unknown"}}) is None


# ---------------------------------------------------------------------------
# Response building: _build_anthropic_response, _build_content_blocks
# ---------------------------------------------------------------------------

class TestBuildAnthropicResponse:
    def test_text_only_response(self):
        openai_result = {
            "choices": [
                {
                    "message": {"content": "Hello there!", "tool_calls": []},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        response = anthropic_compat._build_anthropic_response(openai_result, "claude-test")
        assert response["type"] == "message"
        assert response["role"] == "assistant"
        assert response["model"] == "claude-test"
        assert response["content"] == [{"type": "text", "text": "Hello there!"}]
        assert response["stop_reason"] == "end_turn"
        assert response["stop_sequence"] is None
        assert response["usage"] == {"input_tokens": 10, "output_tokens": 5}

    def test_tool_use_response(self):
        openai_result = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "toolu_1",
                                "function": {
                                    "name": "search",
                                    "arguments": '{"query": "weather"}',
                                },
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {},
        }
        response = anthropic_compat._build_anthropic_response(openai_result, "claude-test")
        assert response["stop_reason"] == "tool_use"
        assert len(response["content"]) == 1
        block = response["content"][0]
        assert block["type"] == "tool_use"
        assert block["id"] == "toolu_1"
        assert block["name"] == "search"
        assert block["input"] == {"query": "weather"}

    def test_text_and_tool_use_response(self):
        openai_result = {
            "choices": [
                {
                    "message": {
                        "content": "Let me search.",
                        "tool_calls": [
                            {
                                "id": "toolu_1",
                                "function": {
                                    "name": "search",
                                    "arguments": '{"q": "test"}',
                                },
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {},
        }
        response = anthropic_compat._build_anthropic_response(openai_result, "claude-test")
        assert response["stop_reason"] == "tool_use"
        assert response["content"][0] == {"type": "text", "text": "Let me search."}
        assert response["content"][1]["type"] == "tool_use"

    def test_preserves_newlines_in_text_content(self):
        openai_result = {
            "choices": [
                {
                    "message": {
                        "content": "# Report\n\nLine one\n\nLine two",
                        "tool_calls": [],
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {},
        }
        response = anthropic_compat._build_anthropic_response(openai_result, "claude-test")
        assert response["content"] == [
            {"type": "text", "text": "# Report\n\nLine one\n\nLine two"}
        ]

    def test_empty_message_produces_empty_text_block(self):
        openai_result = {
            "choices": [
                {
                    "message": {"content": None, "tool_calls": []},
                    "finish_reason": "stop",
                }
            ],
            "usage": {},
        }
        response = anthropic_compat._build_anthropic_response(openai_result, "claude-test")
        assert response["content"] == [{"type": "text", "text": ""}]

    def test_invalid_tool_arguments_fallback_to_empty_dict(self):
        openai_result = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "toolu_1",
                                "function": {
                                    "name": "search",
                                    "arguments": "not valid json",
                                },
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {},
        }
        response = anthropic_compat._build_anthropic_response(openai_result, "claude-test")
        assert response["content"][0]["input"] == {}


# ---------------------------------------------------------------------------
# Stop reason mapping: _map_stop_reason
# ---------------------------------------------------------------------------

class TestMapStopReason:
    def test_length(self):
        reason, seq = anthropic_compat._map_stop_reason("length")
        assert reason == "max_tokens"
        assert seq is None

    def test_tool_calls(self):
        reason, seq = anthropic_compat._map_stop_reason("tool_calls")
        assert reason == "tool_use"
        assert seq is None

    def test_stop_without_sequences(self):
        reason, seq = anthropic_compat._map_stop_reason("stop")
        assert reason == "end_turn"
        assert seq is None

    def test_stop_with_matching_sequence(self):
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=["\n\nHuman:"],
            content_text="Hello\n\nHuman:",
        )
        assert reason == "stop_sequence"
        assert seq == "\n\nHuman:"

    def test_stop_with_non_matching_sequence(self):
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=["\n\nHuman:"],
            content_text="Hello world",
        )
        # Falls back to first sequence when sequences are provided but none match
        assert reason == "stop_sequence"
        assert seq == "\n\nHuman:"

    def test_stop_with_sequences_but_no_content(self):
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=["\n\nHuman:"],
            content_text=None,
        )
        assert reason == "stop_sequence"
        assert seq == "\n\nHuman:"

    def test_unknown_reason_defaults_to_end_turn(self):
        reason, seq = anthropic_compat._map_stop_reason("unknown_reason")
        assert reason == "end_turn"
        assert seq is None


# ---------------------------------------------------------------------------
# Streaming: _anthropic_stream_converter
# ---------------------------------------------------------------------------

class TestAnthropicStreamConverter:
    @pytest.mark.asyncio
    async def test_text_only_stream(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": " world"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "claude-test")
        ]
        joined = "".join(events)

        # Should have message_start
        assert '"type": "message_start"' in joined
        # Should have content_block_start with text type
        assert '"type": "content_block_start"' in joined
        assert '"type": "text"' in joined
        # Should have text deltas
        assert '"type": "text_delta"' in joined
        assert "Hello" in joined
        assert " world" in joined
        # Should have content_block_stop
        assert '"type": "content_block_stop"' in joined
        # Should have message_delta with stop_reason
        assert '"stop_reason": "end_turn"' in joined
        # Should have message_stop
        assert '"type": "message_stop"' in joined

    @pytest.mark.asyncio
    async def test_tool_use_stream(self):
        async def response_stream():
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "toolu_1", "function": '
                '{"name": "search", "arguments": ""}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "function": '
                '{"arguments": "{\\"q\\": \\"test\\"}"}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], '
                '"usage": {"prompt_tokens": 5, "completion_tokens": 10}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "claude-test")
        ]
        joined = "".join(events)

        assert '"type": "tool_use"' in joined
        assert '"id": "toolu_1"' in joined
        assert '"name": "search"' in joined
        assert '"type": "input_json_delta"' in joined
        assert '"stop_reason": "tool_use"' in joined

    @pytest.mark.asyncio
    async def test_text_then_tool_stream(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Let me check."}}]}\n\n'
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "toolu_1", "function": '
                '{"name": "search", "arguments": "{\\"q\\": \\"test\\"}"}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], '
                '"usage": {"prompt_tokens": 5, "completion_tokens": 10}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "claude-test")
        ]
        joined = "".join(events)

        # Text block should be opened and closed before tool block
        assert "Let me check." in joined
        assert '"type": "tool_use"' in joined
        assert '"stop_reason": "tool_use"' in joined

    @pytest.mark.asyncio
    async def test_done_sentinel_ignored(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: [DONE]\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "claude-test")
        ]
        joined = "".join(events)

        assert "Hi" in joined
        assert "[DONE]" not in joined

    @pytest.mark.asyncio
    async def test_stream_with_stop_sequences(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hello\\n\\nHuman:"}}]}\n\n'
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
                '"usage": {"prompt_tokens": 5, "completion_tokens": 2}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(
                response_stream(), "claude-test",
                stop_sequences=["\n\nHuman:"],
            )
        ]
        joined = "".join(events)

        assert '"stop_reason": "stop_sequence"' in joined

    @pytest.mark.asyncio
    async def test_stream_usage_reported(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "X"}}]}\n\n'
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
                '"usage": {"prompt_tokens": 42, "completion_tokens": 7}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "claude-test")
        ]
        joined = "".join(events)

        # Find the message_delta event and check usage
        for event in events:
            if '"type": "message_delta"' in event:
                data_line = [l for l in event.strip().split("\n") if l.startswith("data: ")][0]
                payload = json.loads(data_line[6:])
                assert payload["usage"]["input_tokens"] == 42
                assert payload["usage"]["output_tokens"] == 7
                break
        else:
            pytest.fail("No message_delta event found")

    @pytest.mark.asyncio
    async def test_empty_stream_produces_valid_envelope(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 0, "completion_tokens": 0}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "claude-test")
        ]
        joined = "".join(events)

        assert '"type": "message_start"' in joined
        assert '"type": "message_delta"' in joined
        assert '"type": "message_stop"' in joined

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_stream(self):
        async def response_stream():
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "toolu_1", "function": '
                '{"name": "search", "arguments": "{\\"q\\": \\"a\\"}"}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 1, "id": "toolu_2", "function": '
                '{"name": "calc", "arguments": "{\\"expr\\": \\"1+1\\"}"}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], '
                '"usage": {"prompt_tokens": 5, "completion_tokens": 10}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "claude-test")
        ]
        joined = "".join(events)

        assert '"name": "search"' in joined
        assert '"name": "calc"' in joined
        assert joined.count('"type": "content_block_start"') == 2
        assert '"stop_reason": "tool_use"' in joined


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

class TestSseEvent:
    def test_event_format(self):
        result = anthropic_compat._sse_event("message_start", {"type": "message_start"})
        assert result.startswith("event: message_start\n")
        assert "data: " in result
        assert result.endswith("\n\n")
        payload = json.loads(result.split("data: ")[1].strip())
        assert payload == {"type": "message_start"}


# ---------------------------------------------------------------------------
# Error responses
# ---------------------------------------------------------------------------

class TestAnthropicError:
    def test_error_format(self):
        resp = anthropic_compat._anthropic_error(400, "bad request")
        assert resp.status_code == 400
        body = json.loads(resp.body.decode())
        assert body == {
            "type": "error",
            "error": {"type": "invalid_request_error", "message": "bad request"},
        }

    def test_error_401(self):
        resp = anthropic_compat._anthropic_error(401, "unauthorized")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "authentication_error"

    def test_error_429(self):
        resp = anthropic_compat._anthropic_error(429, "rate limited")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "rate_limit_error"

    def test_error_custom_type(self):
        resp = anthropic_compat._anthropic_error(500, "oops", error_type="custom_error")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "custom_error"

    def test_error_unknown_status(self):
        resp = anthropic_compat._anthropic_error(418, "teapot")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "api_error"


# ---------------------------------------------------------------------------
# Chunk utilities
# ---------------------------------------------------------------------------

class TestChunkUtilities:
    def test_get_chunk_content(self):
        chunk = {"choices": [{"delta": {"content": "hello"}}]}
        assert anthropic_compat._get_chunk_content(chunk) == "hello"

    def test_get_chunk_content_missing(self):
        chunk = {"choices": [{"delta": {}}]}
        assert anthropic_compat._get_chunk_content(chunk) == ""

    def test_get_chunk_tool_calls(self):
        tc = [{"index": 0, "id": "t1", "function": {"name": "f"}}]
        chunk = {"choices": [{"delta": {"tool_calls": tc}}]}
        assert anthropic_compat._get_chunk_tool_calls(chunk) == tc

    def test_get_chunk_tool_calls_missing(self):
        chunk = {"choices": [{"delta": {}}]}
        assert anthropic_compat._get_chunk_tool_calls(chunk) == []

    def test_get_chunk_usage(self):
        chunk = {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        assert anthropic_compat._get_chunk_usage(chunk) == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }

    def test_get_chunk_usage_missing(self):
        chunk = {}
        usage = anthropic_compat._get_chunk_usage(chunk)
        assert usage["prompt_tokens"] == 0
        assert usage["completion_tokens"] == 0


# ===========================================================================
# Integration tests — route handlers via FastAPI TestClient
# ===========================================================================

# Build a lightweight FastAPI app containing only the Anthropic-compat router.
# The real ``mapper`` and ``llm`` modules are stubbed at the top of this file,
# so we patch functions/classes directly on the ``anthropic_compat`` module.

from fastapi import FastAPI
from starlette.testclient import TestClient
from unittest.mock import AsyncMock

_integration_app = FastAPI()
_integration_app.include_router(anthropic_compat.anthropic_compatible_routes)


def _make_client(auth_key=None):
    """Return a TestClient.  When *auth_key* is given, configure BOOST_AUTH
    so the route enforces authentication."""
    import config as _cfg
    if auth_key:
        _cfg.BOOST_AUTH = [auth_key]
    else:
        _cfg.BOOST_AUTH = []
    return TestClient(_integration_app, raise_server_exceptions=False)


# Canonical Anthropic request body used across integration tests.
_ANTHRO_BODY = {
    "model": "claude-test",
    "max_tokens": 128,
    "messages": [{"role": "user", "content": "Hello, world!"}],
}


def _fake_openai_result(content="Hi!", finish_reason="stop",
                         prompt_tokens=10, completion_tokens=5,
                         tool_calls=None):
    """Build a minimal OpenAI-shaped chat completion result."""
    msg = {"content": content, "tool_calls": tool_calls or []}
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "test-model",
        "choices": [{"index": 0, "message": msg, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


class _FakeLLM:
    """Minimal stand-in for llm.LLM used in integration tests."""

    def __init__(self, stream_chunks=None, consume_result=None,
                 chat_completion_result=None, **kwargs):
        self._stream_chunks = stream_chunks or []
        self._consume_result = consume_result
        self._chat_completion_result = chat_completion_result
        self.workflow = kwargs.get("workflow")
        self.boost_params = kwargs.get("params", {})
        self.module = kwargs.get("module")
        self.model = kwargs.get("model", "test-model")
        self.chat = type("Chat", (), {
            "has_substring": lambda self, s: False,
            "history": lambda self: [],
        })()

    async def serve(self):
        async def _gen():
            for chunk in self._stream_chunks:
                yield chunk
        return _gen()

    async def consume_stream(self, stream):
        # Drain the stream
        async for _ in stream:
            pass
        return self._consume_result

    async def chat_completion(self):
        return self._chat_completion_result


# ---------------------------------------------------------------------------
# Auth integration
# ---------------------------------------------------------------------------

class TestIntegrationAuth:
    """Test that the route enforces API key authentication."""

    def test_missing_auth_returns_403(self):
        client = _make_client(auth_key="sk-secret")
        resp = client.post("/v1/messages", json=_ANTHRO_BODY)
        assert resp.status_code == 403

    def test_wrong_api_key_returns_403(self):
        client = _make_client(auth_key="sk-secret")
        resp = client.post(
            "/v1/messages", json=_ANTHRO_BODY,
            headers={"x-api-key": "sk-wrong"},
        )
        assert resp.status_code == 403

    def test_correct_x_api_key_passes_auth(self):
        fake_llm = _FakeLLM(
            consume_result=_fake_openai_result(),
            stream_chunks=[],
        )
        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = _make_client(auth_key="sk-secret")
            resp = client.post(
                "/v1/messages", json=_ANTHRO_BODY,
                headers={"x-api-key": "sk-secret"},
            )
            assert resp.status_code == 200

    def test_correct_bearer_passes_auth(self):
        fake_llm = _FakeLLM(
            consume_result=_fake_openai_result(),
            stream_chunks=[],
        )
        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = _make_client(auth_key="sk-secret")
            resp = client.post(
                "/v1/messages", json=_ANTHRO_BODY,
                headers={"Authorization": "Bearer sk-secret"},
            )
            assert resp.status_code == 200

    def test_no_auth_configured_allows_all(self):
        fake_llm = _FakeLLM(
            consume_result=_fake_openai_result(),
            stream_chunks=[],
        )
        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = _make_client(auth_key=None)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Validation integration
# ---------------------------------------------------------------------------

class TestIntegrationValidation:
    """Test that request validation errors are returned as Anthropic errors."""

    def setup_method(self):
        import config as _cfg
        _cfg.BOOST_AUTH = []

    def test_missing_model_returns_400(self):
        client = TestClient(_integration_app, raise_server_exceptions=False)
        resp = client.post("/v1/messages", json={
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 400
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "invalid_request_error"
        assert "model" in body["error"]["message"]

    def test_missing_max_tokens_returns_400(self):
        client = TestClient(_integration_app, raise_server_exceptions=False)
        resp = client.post("/v1/messages", json={
            "model": "test",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 400
        body = resp.json()
        assert "max_tokens" in body["error"]["message"]

    def test_empty_messages_returns_400(self):
        client = TestClient(_integration_app, raise_server_exceptions=False)
        resp = client.post("/v1/messages", json={
            "model": "test",
            "max_tokens": 128,
            "messages": [],
        })
        assert resp.status_code == 400

    def test_system_role_in_messages_returns_400(self):
        client = TestClient(_integration_app, raise_server_exceptions=False)
        resp = client.post("/v1/messages", json={
            "model": "test",
            "max_tokens": 128,
            "messages": [{"role": "system", "content": "you are helpful"}],
        })
        assert resp.status_code == 400
        body = resp.json()
        assert "system" in body["error"]["message"].lower()

    def test_invalid_json_body_returns_400(self):
        client = TestClient(_integration_app, raise_server_exceptions=False)
        resp = client.post(
            "/v1/messages",
            content=b"not json at all",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "JSON" in body["error"]["message"]


# ---------------------------------------------------------------------------
# Non-streaming POST /v1/messages
# ---------------------------------------------------------------------------

class TestIntegrationNonStreaming:
    """Test the non-streaming path through post_messages."""

    def setup_method(self):
        import config as _cfg
        _cfg.BOOST_AUTH = []

    def test_basic_non_streaming_response_format(self):
        openai_result = _fake_openai_result(
            content="Hello from the backend!",
            finish_reason="stop",
            prompt_tokens=15,
            completion_tokens=8,
        )
        fake_llm = _FakeLLM(consume_result=openai_result, stream_chunks=[])

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)

        assert resp.status_code == 200
        body = resp.json()

        # Verify Anthropic response envelope
        assert body["type"] == "message"
        assert body["role"] == "assistant"
        assert body["model"] == "claude-test"
        assert body["id"].startswith("msg_")
        assert body["stop_reason"] == "end_turn"
        assert body["stop_sequence"] is None

        # Verify content blocks
        assert len(body["content"]) == 1
        assert body["content"][0]["type"] == "text"
        assert body["content"][0]["text"] == "Hello from the backend!"

        # Verify usage
        assert body["usage"]["input_tokens"] == 15
        assert body["usage"]["output_tokens"] == 8

    def test_non_streaming_with_tool_use(self):
        openai_result = _fake_openai_result(
            content=None,
            finish_reason="tool_calls",
            tool_calls=[{
                "id": "toolu_abc",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "NYC"}',
                },
            }],
        )
        fake_llm = _FakeLLM(consume_result=openai_result, stream_chunks=[])

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)

        body = resp.json()
        assert body["stop_reason"] == "tool_use"
        tool_block = body["content"][0]
        assert tool_block["type"] == "tool_use"
        assert tool_block["id"] == "toolu_abc"
        assert tool_block["name"] == "get_weather"
        assert tool_block["input"] == {"location": "NYC"}

    def test_non_streaming_none_completion_returns_500(self):
        fake_llm = _FakeLLM(stream_chunks=[])
        # Override serve to return None
        fake_llm.serve = AsyncMock(return_value=None)

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)

        assert resp.status_code == 500
        body = resp.json()
        assert body["type"] == "error"
        assert "No completion" in body["error"]["message"]

    def test_non_streaming_direct_task(self):
        """When mapper.is_direct_task is True, LLM.chat_completion() is
        used instead of serve()+consume_stream()."""
        openai_result = _fake_openai_result(content="Title suggestion")
        fake_llm = _FakeLLM(chat_completion_result=openai_result)
        fake_llm.workflow = None
        fake_llm.boost_params = {}

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=True)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)

        assert resp.status_code == 200
        body = resp.json()
        assert body["content"][0]["text"] == "Title suggestion"

    def test_mapper_resolve_receives_openai_body(self):
        """Verify that the request body is converted to OpenAI format before
        being passed to mapper.resolve_request_config."""
        openai_result = _fake_openai_result()
        fake_llm = _FakeLLM(consume_result=openai_result, stream_chunks=[])

        captured_body = {}

        def capture_config(body):
            captured_body.update(body)
            return {}

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(side_effect=capture_config)
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            client.post("/v1/messages", json={
                **_ANTHRO_BODY,
                "system": "You are helpful.",
                "temperature": 0.7,
            })

        # The converted body should have OpenAI-format messages
        assert captured_body["model"] == "claude-test"
        assert captured_body["max_tokens"] == 128
        assert captured_body["temperature"] == 0.7
        assert captured_body["messages"][0] == {"role": "system", "content": "You are helpful."}
        assert captured_body["messages"][1] == {"role": "user", "content": "Hello, world!"}


# ---------------------------------------------------------------------------
# Streaming POST /v1/messages
# ---------------------------------------------------------------------------

class TestIntegrationStreaming:
    """Test the streaming SSE path through post_messages."""

    def setup_method(self):
        import config as _cfg
        _cfg.BOOST_AUTH = []

    def _stream_chunks(self):
        """Return typical OpenAI-format SSE chunks as strings."""
        return [
            'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n',
            'data: {"choices": [{"delta": {"content": " there"}}]}\n\n',
            'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
            '"usage": {"prompt_tokens": 10, "completion_tokens": 3}}\n\n',
            'data: [DONE]\n\n',
        ]

    def test_streaming_returns_event_stream(self):
        fake_llm = _FakeLLM(stream_chunks=self._stream_chunks())

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json={**_ANTHRO_BODY, "stream": True})

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_streaming_event_sequence(self):
        fake_llm = _FakeLLM(stream_chunks=self._stream_chunks())

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json={**_ANTHRO_BODY, "stream": True})

        raw = resp.text
        events = _parse_sse_events(raw)
        event_types = [e["type"] for e in events]

        # Verify canonical Anthropic SSE event ordering
        assert event_types[0] == "message_start"
        assert "content_block_start" in event_types
        assert "content_block_delta" in event_types
        assert "content_block_stop" in event_types
        assert "message_delta" in event_types
        assert event_types[-1] == "message_stop"

    def test_streaming_text_content(self):
        fake_llm = _FakeLLM(stream_chunks=self._stream_chunks())

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json={**_ANTHRO_BODY, "stream": True})

        raw = resp.text
        events = _parse_sse_events(raw)

        # Collect all text_delta content
        text_deltas = [
            e["delta"]["text"]
            for e in events
            if e.get("type") == "content_block_delta"
            and e.get("delta", {}).get("type") == "text_delta"
        ]
        assert "".join(text_deltas) == "Hello there"

    def test_streaming_usage_in_message_delta(self):
        fake_llm = _FakeLLM(stream_chunks=self._stream_chunks())

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json={**_ANTHRO_BODY, "stream": True})

        events = _parse_sse_events(resp.text)
        message_delta = [e for e in events if e.get("type") == "message_delta"][0]
        assert message_delta["usage"]["input_tokens"] == 10
        assert message_delta["usage"]["output_tokens"] == 3
        assert message_delta["delta"]["stop_reason"] == "end_turn"

    def test_streaming_tool_use_events(self):
        chunks = [
            'data: {"choices": [{"delta": {"tool_calls": ['
            '{"index": 0, "id": "toolu_xyz", "function": '
            '{"name": "calculator", "arguments": ""}}]}}]}\n\n',
            'data: {"choices": [{"delta": {"tool_calls": ['
            '{"index": 0, "function": '
            '{"arguments": "{\\"expr\\": \\"2+2\\"}"}}]}}]}\n\n',
            'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], '
            '"usage": {"prompt_tokens": 5, "completion_tokens": 10}}\n\n',
        ]
        fake_llm = _FakeLLM(stream_chunks=chunks)

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json={**_ANTHRO_BODY, "stream": True})

        events = _parse_sse_events(resp.text)
        event_types = [e["type"] for e in events]

        assert "content_block_start" in event_types
        # Find the tool content_block_start
        tool_start = [
            e for e in events
            if e.get("type") == "content_block_start"
            and e.get("content_block", {}).get("type") == "tool_use"
        ]
        assert len(tool_start) == 1
        assert tool_start[0]["content_block"]["id"] == "toolu_xyz"
        assert tool_start[0]["content_block"]["name"] == "calculator"

        # Verify message_delta has tool_use stop reason
        message_delta = [e for e in events if e.get("type") == "message_delta"][0]
        assert message_delta["delta"]["stop_reason"] == "tool_use"


# ---------------------------------------------------------------------------
# POST /v1/messages/count_tokens
# ---------------------------------------------------------------------------

class TestIntegrationCountTokens:
    """Test the count_tokens endpoint."""

    def setup_method(self):
        import config as _cfg
        _cfg.BOOST_AUTH = []

    def test_count_tokens_returns_input_tokens(self):
        openai_result = _fake_openai_result(prompt_tokens=42, completion_tokens=1)
        fake_llm = _FakeLLM(consume_result=openai_result, stream_chunks=[])

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages/count_tokens", json={
                "model": "claude-test",
                "messages": [{"role": "user", "content": "Count me"}],
            })

        assert resp.status_code == 200
        body = resp.json()
        assert body == {"input_tokens": 42}

    def test_count_tokens_missing_model_returns_400(self):
        client = TestClient(_integration_app, raise_server_exceptions=False)
        resp = client.post("/v1/messages/count_tokens", json={
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 400
        body = resp.json()
        assert "model" in body["error"]["message"]

    def test_count_tokens_empty_messages_returns_400(self):
        client = TestClient(_integration_app, raise_server_exceptions=False)
        resp = client.post("/v1/messages/count_tokens", json={
            "model": "test",
            "messages": [],
        })
        assert resp.status_code == 400

    def test_count_tokens_auth_enforced(self):
        client = _make_client(auth_key="sk-token")
        resp = client.post("/v1/messages/count_tokens", json={
            "model": "test",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 403

    def test_count_tokens_none_completion_returns_500(self):
        fake_llm = _FakeLLM(stream_chunks=[])
        fake_llm.serve = AsyncMock(return_value=None)

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages/count_tokens", json={
                "model": "test",
                "messages": [{"role": "user", "content": "hi"}],
            })

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Mapper error propagation
# ---------------------------------------------------------------------------

class TestMapperErrorPropagation:
    """Test that mapper errors are returned as Anthropic-format errors."""

    def setup_method(self):
        import config as _cfg
        _cfg.BOOST_AUTH = []

    def test_unknown_model_returns_404_anthropic_error(self):
        """When mapper.resolve_request_config raises HTTPException(404),
        the response should be Anthropic-format not_found_error."""
        from fastapi import HTTPException as FastAPIHTTPException

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(
                side_effect=FastAPIHTTPException(
                    status_code=404,
                    detail="Unknown model: 'nonexistent-model'",
                )
            )

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json={
                **_ANTHRO_BODY,
                "model": "nonexistent-model",
            })

        assert resp.status_code == 404
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "not_found_error"
        assert "nonexistent-model" in body["error"]["message"]

    def test_unknown_model_in_count_tokens_returns_404(self):
        """count_tokens endpoint should also return Anthropic-format 404."""
        from fastapi import HTTPException as FastAPIHTTPException

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(
                side_effect=FastAPIHTTPException(
                    status_code=404,
                    detail="Unknown model: 'bad-model'",
                )
            )

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages/count_tokens", json={
                "model": "bad-model",
                "messages": [{"role": "user", "content": "hi"}],
            })

        assert resp.status_code == 404
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "not_found_error"

    def test_value_error_returns_400_anthropic_error(self):
        """When mapper raises ValueError (no model specifier),
        the response should be Anthropic-format invalid_request_error."""
        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(
                side_effect=ValueError("Unable to proxy request without a model specifier")
            )

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)

        assert resp.status_code == 400
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "invalid_request_error"
        assert "model" in body["error"]["message"].lower()

    def test_value_error_in_count_tokens_returns_400(self):
        """count_tokens endpoint should also return 400 for ValueError."""
        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(
                side_effect=ValueError("Unable to proxy request without a model specifier")
            )

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages/count_tokens", json={
                "model": "test",
                "messages": [{"role": "user", "content": "hi"}],
            })

        assert resp.status_code == 400
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "invalid_request_error"

    def test_generic_exception_returns_500(self):
        """Unexpected exceptions should return Anthropic-format 500."""
        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
        ):
            mock_mapper.list_downstream = AsyncMock(
                side_effect=RuntimeError("connection lost")
            )

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)

        assert resp.status_code == 500
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "api_error"


# ---------------------------------------------------------------------------
# Response headers
# ---------------------------------------------------------------------------

class TestResponseHeaders:
    """Test that responses include expected headers."""

    def setup_method(self):
        import config as _cfg
        _cfg.BOOST_AUTH = []

    def test_non_streaming_has_request_id(self):
        """Non-streaming responses should include x-request-id header."""
        fake_llm = _FakeLLM(
            consume_result=_fake_openai_result(),
            stream_chunks=[],
        )

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)

        assert resp.status_code == 200
        assert "request-id" in resp.headers
        assert resp.headers["request-id"].startswith("req_")

    def test_streaming_has_request_id(self):
        """Streaming responses should include x-request-id header."""
        chunks = [
            'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n',
            'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
            '"usage": {"prompt_tokens": 5, "completion_tokens": 1}}\n\n',
        ]
        fake_llm = _FakeLLM(stream_chunks=chunks)

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json={**_ANTHRO_BODY, "stream": True})

        assert resp.status_code == 200
        assert "request-id" in resp.headers
        assert resp.headers["request-id"].startswith("req_")

    def test_non_streaming_content_type_is_json(self):
        """Non-streaming responses should have application/json content type."""
        fake_llm = _FakeLLM(
            consume_result=_fake_openai_result(),
            stream_chunks=[],
        )

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)

        assert "application/json" in resp.headers.get("content-type", "")

    def test_direct_task_has_request_id(self):
        """Direct task responses should also include x-request-id."""
        openai_result = _fake_openai_result(content="Title")
        fake_llm = _FakeLLM(chat_completion_result=openai_result)
        fake_llm.workflow = None
        fake_llm.boost_params = {}

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=True)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)

        assert resp.status_code == 200
        assert "request-id" in resp.headers

    def test_count_tokens_has_request_id(self):
        """count_tokens responses should include x-request-id."""
        openai_result = _fake_openai_result(prompt_tokens=20)
        fake_llm = _FakeLLM(consume_result=openai_result, stream_chunks=[])

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages/count_tokens", json={
                "model": "test",
                "messages": [{"role": "user", "content": "hi"}],
            })

        assert resp.status_code == 200
        assert "request-id" in resp.headers


# ---------------------------------------------------------------------------
# Stream edge cases
# ---------------------------------------------------------------------------

class TestStreamEdgeCases:
    """Test edge cases in the streaming conversion."""

    @pytest.mark.asyncio
    async def test_empty_tool_calls_array_in_chunk(self):
        """An empty tool_calls array in a chunk should not cause errors."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hello", "tool_calls": []}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert "Hello" in joined
        assert '"type": "message_stop"' in joined
        # No tool_use blocks should appear
        assert '"type": "tool_use"' not in joined

    @pytest.mark.asyncio
    async def test_malformed_json_chunks_skipped(self):
        """Chunks with malformed JSON after 'data: ' should be silently skipped."""
        async def response_stream():
            yield 'data: not valid json at all\n\n'
            yield 'data: {"choices": [{"delta": {"content": "OK"}}]}\n\n'
            yield 'data: {truncated\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert "OK" in joined
        assert '"type": "message_stop"' in joined

    @pytest.mark.asyncio
    async def test_mid_stream_exception_emits_error_text(self):
        """If the underlying response stream raises, the converter should
        emit the error as a text block and still produce valid SSE envelope."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "partial"}}]}\n\n'
            raise RuntimeError("backend connection reset")

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        # Should contain the partial content
        assert "partial" in joined
        # Should contain the error text
        assert "Stream error" in joined
        assert "backend connection reset" in joined
        # Should still have valid envelope
        assert '"type": "message_start"' in joined
        assert '"type": "message_delta"' in joined
        assert '"type": "message_stop"' in joined

    @pytest.mark.asyncio
    async def test_mid_stream_exception_without_prior_text_block(self):
        """Error before any content should open a new text block for the error."""
        async def response_stream():
            # Must yield once to be an async generator, but raise before producing data
            if False:
                yield  # pragma: no cover
            raise ConnectionError("refused")

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert '"type": "content_block_start"' in joined
        assert "refused" in joined
        assert '"type": "message_stop"' in joined

    @pytest.mark.asyncio
    async def test_chunk_with_only_finish_reason_no_content(self):
        """A chunk with finish_reason but no content/tool_calls should be safe."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Done"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "length"}], "usage": {"prompt_tokens": 5, "completion_tokens": 100}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert '"stop_reason": "max_tokens"' in joined

    @pytest.mark.asyncio
    async def test_bytes_chunks_handled(self):
        """The converter should handle both str and bytes chunks."""
        async def response_stream():
            yield b'data: {"choices": [{"delta": {"content": "bytes!"}}]}\n\n'
            yield b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert "bytes!" in joined
        assert '"type": "message_stop"' in joined


# ---------------------------------------------------------------------------
# Request field acceptance
# ---------------------------------------------------------------------------

class TestRequestFieldAcceptance:
    """Test that extra/optional Anthropic request fields don't cause errors."""

    def setup_method(self):
        import config as _cfg
        _cfg.BOOST_AUTH = []

    def test_metadata_field_accepted(self):
        """The metadata field should be accepted without error even if unused."""
        fake_llm = _FakeLLM(
            consume_result=_fake_openai_result(),
            stream_chunks=[],
        )

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json={
                **_ANTHRO_BODY,
                "metadata": {"user_id": "user-123"},
            })

        assert resp.status_code == 200

    def test_extra_unknown_fields_accepted(self):
        """Unknown fields should be silently ignored."""
        fake_llm = _FakeLLM(
            consume_result=_fake_openai_result(),
            stream_chunks=[],
        )

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json={
                **_ANTHRO_BODY,
                "top_k": 40,
                "metadata": {"user_id": "u1"},
                "system": [
                    {"type": "text", "text": "You are helpful."},
                    {"type": "text", "text": "Be concise.", "cache_control": {"type": "ephemeral"}},
                ],
            })

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# SDK compatibility — verify response shapes match Anthropic Python SDK models
# ---------------------------------------------------------------------------

class TestSdkCompatMessageStart:
    """Verify message_start event has all fields the SDK's Message model requires."""

    @pytest.mark.asyncio
    async def test_message_start_contains_required_message_fields(self):
        """The message object in message_start must include all required fields
        from the SDK's Message model: id, type, role, model, content, stop_reason,
        stop_sequence, usage."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "my-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)
        msg_start = parsed[0]

        assert msg_start["type"] == "message_start"
        message = msg_start["message"]
        assert "id" in message
        assert message["type"] == "message"
        assert message["role"] == "assistant"
        assert message["model"] == "my-model"
        assert message["content"] == []
        assert message["stop_reason"] is None
        assert message["stop_sequence"] is None
        assert "usage" in message

    @pytest.mark.asyncio
    async def test_message_start_usage_has_output_tokens(self):
        """The usage in message_start must include output_tokens (required by SDK Usage model)."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "X"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)
        usage = parsed[0]["message"]["usage"]

        assert "input_tokens" in usage
        assert "output_tokens" in usage
        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0


class TestSdkCompatMessageDelta:
    """Verify message_delta event matches SDK's RawMessageDeltaEvent model."""

    @pytest.mark.asyncio
    async def test_message_delta_has_required_fields(self):
        """message_delta must have type, delta (with stop_reason), and usage (with output_tokens)."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)
        msg_delta = [e for e in parsed if e.get("type") == "message_delta"][0]

        assert msg_delta["type"] == "message_delta"
        assert "delta" in msg_delta
        assert "stop_reason" in msg_delta["delta"]
        assert "stop_sequence" in msg_delta["delta"]
        assert "usage" in msg_delta
        assert "output_tokens" in msg_delta["usage"]

    @pytest.mark.asyncio
    async def test_message_delta_usage_output_tokens_is_int(self):
        """output_tokens in message_delta usage is required (not optional) in SDK."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "X"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)
        msg_delta = [e for e in parsed if e.get("type") == "message_delta"][0]

        assert isinstance(msg_delta["usage"]["output_tokens"], int)
        assert msg_delta["usage"]["output_tokens"] == 3


class TestSdkCompatMessageStop:
    """Verify message_stop event matches SDK's RawMessageStopEvent."""

    @pytest.mark.asyncio
    async def test_message_stop_only_has_type(self):
        """message_stop should have type: 'message_stop' and nothing else required."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)
        msg_stop = [e for e in parsed if e.get("type") == "message_stop"][0]

        assert msg_stop["type"] == "message_stop"


class TestSdkCompatContentBlocks:
    """Verify content block events match SDK's type discriminators."""

    @pytest.mark.asyncio
    async def test_text_block_start_has_type_text(self):
        """content_block_start for text must have content_block.type == 'text'."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)
        block_start = [e for e in parsed if e.get("type") == "content_block_start"][0]

        assert block_start["content_block"]["type"] == "text"
        assert "text" in block_start["content_block"]
        assert "index" in block_start

    @pytest.mark.asyncio
    async def test_tool_use_block_start_has_required_fields(self):
        """content_block_start for tool_use must have id, name, input, type."""
        async def response_stream():
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "toolu_abc", "function": '
                '{"name": "search", "arguments": ""}}]}}]}\n\n'
            )
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)
        block_start = [
            e for e in parsed
            if e.get("type") == "content_block_start"
            and e.get("content_block", {}).get("type") == "tool_use"
        ][0]

        cb = block_start["content_block"]
        assert cb["type"] == "tool_use"
        assert "id" in cb
        assert "name" in cb
        assert "input" in cb
        assert isinstance(cb["input"], dict)

    @pytest.mark.asyncio
    async def test_text_delta_has_type_text_delta(self):
        """content_block_delta for text must have delta.type == 'text_delta'."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)
        text_delta = [
            e for e in parsed
            if e.get("type") == "content_block_delta"
            and e.get("delta", {}).get("type") == "text_delta"
        ][0]

        assert text_delta["delta"]["type"] == "text_delta"
        assert "text" in text_delta["delta"]
        assert "index" in text_delta

    @pytest.mark.asyncio
    async def test_input_json_delta_has_type_input_json_delta(self):
        """content_block_delta for tool args must have delta.type == 'input_json_delta'."""
        async def response_stream():
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "toolu_1", "function": '
                '{"name": "f", "arguments": ""}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "function": '
                '{"arguments": "{\\"k\\": 1}"}}]}}]}\n\n'
            )
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)
        json_delta = [
            e for e in parsed
            if e.get("type") == "content_block_delta"
            and e.get("delta", {}).get("type") == "input_json_delta"
        ][0]

        assert json_delta["delta"]["type"] == "input_json_delta"
        assert "partial_json" in json_delta["delta"]

    @pytest.mark.asyncio
    async def test_content_block_stop_has_index(self):
        """content_block_stop must have index field."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)
        block_stop = [e for e in parsed if e.get("type") == "content_block_stop"][0]

        assert "index" in block_stop
        assert isinstance(block_stop["index"], int)


class TestSdkCompatNonStreaming:
    """Verify non-streaming response matches SDK's Message model."""

    def test_non_streaming_response_has_all_required_fields(self):
        """Non-streaming response must have all required Message fields."""
        openai_result = {
            "choices": [{
                "message": {"content": "Hello!", "tool_calls": []},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        response = anthropic_compat._build_anthropic_response(openai_result, "test-model")

        # All required fields from SDK's Message model
        assert response["id"].startswith("msg_")
        assert response["type"] == "message"
        assert response["role"] == "assistant"
        assert response["model"] == "test-model"
        assert isinstance(response["content"], list)
        assert response["stop_reason"] in ("end_turn", "max_tokens", "stop_sequence", "tool_use")
        assert "stop_sequence" in response
        assert isinstance(response["usage"], dict)
        assert "input_tokens" in response["usage"]
        assert "output_tokens" in response["usage"]

    def test_response_header_name_matches_sdk(self):
        """The response header must be 'request-id' (not 'x-request-id')
        because the SDK reads headers.get('request-id')."""
        fake_llm = _FakeLLM(
            consume_result=_fake_openai_result(),
            stream_chunks=[],
        )

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            import config as _cfg
            _cfg.BOOST_AUTH = []

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)

        assert resp.status_code == 200
        # SDK reads "request-id", not "x-request-id"
        assert "request-id" in resp.headers
        assert resp.headers["request-id"].startswith("req_")


class TestSdkCompatStreamEventSequence:
    """Verify the full stream event sequence matches what the SDK expects."""

    @pytest.mark.asyncio
    async def test_stream_starts_with_message_start(self):
        """SDK raises RuntimeError if first event is not message_start."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)

        assert parsed[0]["type"] == "message_start"

    @pytest.mark.asyncio
    async def test_stream_ends_with_message_stop(self):
        """The last event must be message_stop."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)

        assert parsed[-1]["type"] == "message_stop"

    @pytest.mark.asyncio
    async def test_message_delta_precedes_message_stop(self):
        """message_delta must come before message_stop."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)

        types = [e["type"] for e in parsed]
        delta_idx = types.index("message_delta")
        stop_idx = types.index("message_stop")
        assert delta_idx < stop_idx


# ---------------------------------------------------------------------------
# Extended Thinking: _convert_params with thinking
# ---------------------------------------------------------------------------

class TestConvertParamsThinking:
    def test_thinking_enabled_sets_max_completion_tokens(self):
        body = {
            "max_tokens": 1024,
            "thinking": {"type": "enabled", "budget_tokens": 10000},
        }
        params = anthropic_compat._convert_params(body)
        assert params["max_completion_tokens"] == 11024
        assert "max_tokens" not in params

    def test_thinking_enabled_with_stream(self):
        body = {
            "max_tokens": 512,
            "thinking": {"type": "enabled", "budget_tokens": 5000},
            "stream": True,
        }
        params = anthropic_compat._convert_params(body)
        assert params["max_completion_tokens"] == 5512
        assert params["stream"] is True
        assert "max_tokens" not in params

    def test_thinking_disabled_uses_max_tokens(self):
        """When thinking is not enabled, max_tokens is passed normally."""
        body = {"max_tokens": 1024}
        params = anthropic_compat._convert_params(body)
        assert params["max_tokens"] == 1024
        assert "max_completion_tokens" not in params

    def test_thinking_wrong_type_uses_max_tokens(self):
        """Invalid thinking type is ignored."""
        body = {
            "max_tokens": 1024,
            "thinking": {"type": "disabled"},
        }
        params = anthropic_compat._convert_params(body)
        assert params["max_tokens"] == 1024
        assert "max_completion_tokens" not in params

    def test_thinking_non_dict_ignored(self):
        body = {
            "max_tokens": 1024,
            "thinking": "invalid",
        }
        params = anthropic_compat._convert_params(body)
        assert params["max_tokens"] == 1024

    def test_thinking_zero_budget(self):
        body = {
            "max_tokens": 1024,
            "thinking": {"type": "enabled", "budget_tokens": 0},
        }
        params = anthropic_compat._convert_params(body)
        assert params["max_completion_tokens"] == 1024


# ---------------------------------------------------------------------------
# Extended Thinking: _build_content_blocks with reasoning
# ---------------------------------------------------------------------------

class TestBuildContentBlocksThinking:
    def test_reasoning_content_produces_thinking_block(self):
        result = _fake_openai_result(content="The answer is 42.")
        result["choices"][0]["message"]["reasoning_content"] = "Let me think step by step..."
        blocks = anthropic_compat._build_content_blocks(result)
        assert len(blocks) == 2
        assert blocks[0]["type"] == "thinking"
        assert blocks[0]["thinking"] == "Let me think step by step..."
        assert blocks[1]["type"] == "text"
        assert blocks[1]["text"] == "The answer is 42."

    def test_reasoning_field_also_works(self):
        """Some backends use 'reasoning' instead of 'reasoning_content'."""
        result = _fake_openai_result(content="Result.")
        result["choices"][0]["message"]["reasoning"] = "Analysis..."
        blocks = anthropic_compat._build_content_blocks(result)
        assert blocks[0]["type"] == "thinking"
        assert blocks[0]["thinking"] == "Analysis..."
        assert blocks[1]["type"] == "text"

    def test_reasoning_content_preferred_over_reasoning(self):
        """reasoning_content takes precedence over reasoning."""
        result = _fake_openai_result(content="Result.")
        result["choices"][0]["message"]["reasoning_content"] = "Primary"
        result["choices"][0]["message"]["reasoning"] = "Fallback"
        blocks = anthropic_compat._build_content_blocks(result)
        assert blocks[0]["thinking"] == "Primary"

    def test_no_reasoning_no_thinking_block(self):
        result = _fake_openai_result(content="Just text.")
        blocks = anthropic_compat._build_content_blocks(result)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"

    def test_reasoning_with_tool_calls(self):
        """Thinking block should appear before text and tool_use blocks."""
        result = _fake_openai_result(
            content="Let me search.",
            tool_calls=[{
                "id": "toolu_1",
                "function": {"name": "search", "arguments": '{"q": "test"}'},
            }],
        )
        result["choices"][0]["message"]["reasoning_content"] = "I need to search."
        blocks = anthropic_compat._build_content_blocks(result)
        assert len(blocks) == 3
        assert blocks[0]["type"] == "thinking"
        assert blocks[1]["type"] == "text"
        assert blocks[2]["type"] == "tool_use"

    def test_reasoning_only_no_text(self):
        """If there's reasoning but no text content, only thinking block is produced."""
        result = _fake_openai_result(content=None)
        result["choices"][0]["message"]["reasoning_content"] = "Thought about it."
        blocks = anthropic_compat._build_content_blocks(result)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "thinking"
        assert blocks[0]["thinking"] == "Thought about it."

    def test_empty_reasoning_no_thinking_block(self):
        """Empty string reasoning should not produce a thinking block."""
        result = _fake_openai_result(content="Answer.")
        result["choices"][0]["message"]["reasoning_content"] = ""
        blocks = anthropic_compat._build_content_blocks(result)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"


# ---------------------------------------------------------------------------
# Extended Thinking: streaming with reasoning content
# ---------------------------------------------------------------------------

class TestStreamingThinking:
    @pytest.mark.asyncio
    async def test_reasoning_then_text_stream(self):
        """Reasoning content should produce thinking blocks before text blocks."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"reasoning_content": "Let me think"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"reasoning_content": " about this."}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": "The answer"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": " is 42."}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 10}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        # Should have message_start
        types = [e.get("type") for e in parsed]
        assert "message_start" in types

        # Find thinking block events
        thinking_starts = [e for e in parsed if e.get("type") == "content_block_start" and e.get("content_block", {}).get("type") == "thinking"]
        assert len(thinking_starts) == 1
        assert thinking_starts[0]["index"] == 0

        # Find thinking deltas
        thinking_deltas = [e for e in parsed if e.get("type") == "content_block_delta" and e.get("delta", {}).get("type") == "thinking_delta"]
        assert len(thinking_deltas) == 2
        assert thinking_deltas[0]["delta"]["thinking"] == "Let me think"
        assert thinking_deltas[1]["delta"]["thinking"] == " about this."

        # Find text block events
        text_starts = [e for e in parsed if e.get("type") == "content_block_start" and e.get("content_block", {}).get("type") == "text"]
        assert len(text_starts) == 1
        assert text_starts[0]["index"] == 1  # after thinking block

        # Find text deltas
        text_deltas = [e for e in parsed if e.get("type") == "content_block_delta" and e.get("delta", {}).get("type") == "text_delta"]
        assert len(text_deltas) == 2
        assert text_deltas[0]["delta"]["text"] == "The answer"
        assert text_deltas[1]["delta"]["text"] == " is 42."

        # Thinking block should be stopped before text starts
        stops = [e for e in parsed if e.get("type") == "content_block_stop"]
        # At least 2 stops: thinking block and text block
        assert len(stops) >= 2

    @pytest.mark.asyncio
    async def test_reasoning_only_stream(self):
        """Stream with only reasoning content and no text."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"reasoning_content": "Thinking..."}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        thinking_starts = [e for e in parsed if e.get("type") == "content_block_start" and e.get("content_block", {}).get("type") == "thinking"]
        assert len(thinking_starts) == 1

        thinking_deltas = [e for e in parsed if e.get("type") == "content_block_delta" and e.get("delta", {}).get("type") == "thinking_delta"]
        assert len(thinking_deltas) == 1
        assert thinking_deltas[0]["delta"]["thinking"] == "Thinking..."

        # Thinking block should be closed
        stops = [e for e in parsed if e.get("type") == "content_block_stop"]
        assert len(stops) >= 1

        # Should still have message_delta and message_stop
        assert '"type": "message_delta"' in joined
        assert '"type": "message_stop"' in joined

    @pytest.mark.asyncio
    async def test_reasoning_via_reasoning_field(self):
        """Some backends use delta.reasoning instead of delta.reasoning_content."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"reasoning": "Alt field."}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": "Done."}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert '"type": "thinking"' in joined
        assert '"type": "thinking_delta"' in joined
        assert "Alt field." in joined

    @pytest.mark.asyncio
    async def test_reasoning_then_tool_calls(self):
        """Reasoning followed by tool calls should close thinking before tools."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"reasoning_content": "I should search."}}]}\n\n'
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "toolu_1", "function": '
                '{"name": "search", "arguments": "{\\"q\\": \\"test\\"}"}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], '
                '"usage": {"prompt_tokens": 5, "completion_tokens": 10}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        # Thinking block should exist
        thinking_starts = [e for e in parsed if e.get("type") == "content_block_start" and e.get("content_block", {}).get("type") == "thinking"]
        assert len(thinking_starts) == 1

        # Tool use block should exist
        tool_starts = [e for e in parsed if e.get("type") == "content_block_start" and e.get("content_block", {}).get("type") == "tool_use"]
        assert len(tool_starts) == 1

        # Thinking block index should be before tool block index
        assert thinking_starts[0]["index"] < tool_starts[0]["index"]

        assert '"stop_reason": "tool_use"' in joined

    @pytest.mark.asyncio
    async def test_no_reasoning_stream_unchanged(self):
        """Streams without reasoning should work exactly as before."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert '"type": "thinking"' not in joined
        assert '"type": "thinking_delta"' not in joined
        assert '"type": "text"' in joined
        assert "Hi" in joined

    @pytest.mark.asyncio
    async def test_thinking_block_indices_are_sequential(self):
        """Block indices should be sequential: thinking=0, text=1."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"reasoning_content": "Think."}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": "Answer."}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        parsed = _parse_sse_events("".join(events))

        block_starts = [e for e in parsed if e.get("type") == "content_block_start"]
        assert block_starts[0]["index"] == 0
        assert block_starts[0]["content_block"]["type"] == "thinking"
        assert block_starts[1]["index"] == 1
        assert block_starts[1]["content_block"]["type"] == "text"


# ---------------------------------------------------------------------------
# Extended Thinking: integration tests
# ---------------------------------------------------------------------------

class TestIntegrationThinking:
    def test_non_streaming_with_reasoning(self):
        """Non-streaming response with reasoning_content produces thinking block."""
        openai_result = _fake_openai_result(content="The answer is 42.")
        openai_result["choices"][0]["message"]["reasoning_content"] = "Let me analyze..."
        fake_llm = _FakeLLM(consume_result=openai_result, stream_chunks=[])

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)

        assert resp.status_code == 200
        body = resp.json()
        assert body["content"][0]["type"] == "thinking"
        assert body["content"][0]["thinking"] == "Let me analyze..."
        assert body["content"][1]["type"] == "text"
        assert body["content"][1]["text"] == "The answer is 42."

    def test_non_streaming_without_reasoning(self):
        """Non-streaming response without reasoning has no thinking block."""
        openai_result = _fake_openai_result(content="Plain answer.")
        fake_llm = _FakeLLM(consume_result=openai_result, stream_chunks=[])

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)

        body = resp.json()
        assert len(body["content"]) == 1
        assert body["content"][0]["type"] == "text"

    def test_streaming_with_reasoning(self):
        """Streaming response with reasoning_content produces thinking events."""
        chunks = [
            'data: {"choices": [{"delta": {"reasoning_content": "Reasoning..."}}]}\n\n',
            'data: {"choices": [{"delta": {"content": "Answer."}}]}\n\n',
            'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
            '"usage": {"prompt_tokens": 5, "completion_tokens": 3}}\n\n',
        ]
        fake_llm = _FakeLLM(stream_chunks=chunks)

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json={**_ANTHRO_BODY, "stream": True})

        assert resp.status_code == 200
        text = resp.text
        assert '"type": "thinking"' in text
        assert '"type": "thinking_delta"' in text
        assert "Reasoning..." in text
        assert "Answer." in text

    def test_thinking_param_forwarded(self):
        """The thinking parameter should cause max_completion_tokens in the OpenAI body."""
        fake_llm = _FakeLLM(
            consume_result=_fake_openai_result(content="Done."),
            stream_chunks=[],
        )

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            body_with_thinking = {
                **_ANTHRO_BODY,
                "thinking": {"type": "enabled", "budget_tokens": 8000},
            }
            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=body_with_thinking)

        assert resp.status_code == 200
        # Verify the OpenAI body was built with max_completion_tokens
        call_args = mock_mapper.resolve_request_config.call_args[0][0]
        assert call_args.get("max_completion_tokens") == 8128  # 8000 + 128
        assert "max_tokens" not in call_args

    def test_direct_task_with_reasoning(self):
        """Direct task with reasoning_content produces thinking block."""
        openai_result = _fake_openai_result(content="Title")
        openai_result["choices"][0]["message"]["reasoning_content"] = "Considering..."
        fake_llm = _FakeLLM(chat_completion_result=openai_result)
        fake_llm.workflow = None
        fake_llm.boost_params = {}

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=True)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json=_ANTHRO_BODY)

        body = resp.json()
        assert body["content"][0]["type"] == "thinking"
        assert body["content"][1]["type"] == "text"


# ---------------------------------------------------------------------------
# Extended Thinking: compat_utils.get_chunk_reasoning
# ---------------------------------------------------------------------------

class TestGetChunkReasoning:
    def test_reasoning_content_field(self):
        from compat_utils import get_chunk_reasoning
        chunk = {"choices": [{"delta": {"reasoning_content": "thinking..."}}]}
        assert get_chunk_reasoning(chunk) == "thinking..."

    def test_reasoning_field(self):
        from compat_utils import get_chunk_reasoning
        chunk = {"choices": [{"delta": {"reasoning": "alt thinking..."}}]}
        assert get_chunk_reasoning(chunk) == "alt thinking..."

    def test_reasoning_content_preferred(self):
        from compat_utils import get_chunk_reasoning
        chunk = {"choices": [{"delta": {"reasoning_content": "primary", "reasoning": "fallback"}}]}
        assert get_chunk_reasoning(chunk) == "primary"

    def test_no_reasoning(self):
        from compat_utils import get_chunk_reasoning
        chunk = {"choices": [{"delta": {"content": "just text"}}]}
        assert get_chunk_reasoning(chunk) == ""

    def test_empty_chunk(self):
        from compat_utils import get_chunk_reasoning
        assert get_chunk_reasoning({}) == ""


# ---------------------------------------------------------------------------
# SSE parsing helper
# ---------------------------------------------------------------------------

def _parse_sse_events(raw_text):
    """Parse raw SSE text into a list of data payloads (dicts)."""
    events = []
    for block in raw_text.strip().split("\n\n"):
        data_line = None
        for line in block.strip().split("\n"):
            if line.startswith("data: "):
                data_line = line[6:]
        if data_line:
            try:
                events.append(json.loads(data_line))
            except json.JSONDecodeError:
                pass
    return events


if __name__ == "__main__":
    unittest.main()
