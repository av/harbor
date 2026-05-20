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
        # toolu_ prefix is normalized to call_ for the OpenAI backend
        assert msgs[0] == {
            "role": "tool",
            "tool_call_id": "call_1",
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
        # toolu_ prefix normalized to call_ for OpenAI backend
        assert msgs[0]["tool_calls"] == [
            {
                "id": "call_1",
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

    def test_assistant_message_thinking_blocks_stripped(self):
        """Thinking blocks in assistant message history should be silently skipped."""
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "Let me analyze..."},
                        {"type": "text", "text": "The answer is 42."},
                    ],
                }
            ],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["content"] == "The answer is 42."
        assert "tool_calls" not in msgs[0]

    def test_assistant_message_thinking_only_stripped(self):
        """Assistant message with only thinking blocks produces a valid message with None content."""
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "Deep internal reasoning..."},
                    ],
                }
            ],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["content"] is None

    def test_assistant_message_thinking_with_tool_use(self):
        """Thinking blocks alongside tool_use blocks should be stripped, tool_use preserved."""
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "I need to search for this."},
                        {"type": "tool_use", "id": "toolu_1", "name": "search", "input": {"q": "test"}},
                    ],
                }
            ],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["content"] is None
        assert len(msgs[0]["tool_calls"]) == 1
        assert msgs[0]["tool_calls"][0]["function"]["name"] == "search"

    def test_assistant_message_thinking_text_and_tool_use(self):
        """All three block types: thinking stripped, text and tool_use preserved."""
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "Reasoning here."},
                        {"type": "text", "text": "I found something."},
                        {"type": "tool_use", "id": "toolu_1", "name": "fetch", "input": {"url": "http://example.com"}},
                    ],
                }
            ],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "I found something."
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
        # toolu_ prefix normalized to call_ for OpenAI backend
        assert openai_body["messages"][0]["tool_calls"][0] == {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "memory_recall",
                "arguments": "{}",
            },
        }
        assert openai_body["messages"][1] == {
            "role": "tool",
            "tool_call_id": "call_1",
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

    def test_disable_parallel_tool_use_does_not_affect_choice(self):
        # disable_parallel_tool_use is handled in _build_openai_body, not here
        result = anthropic_compat._convert_tool_choice(
            {"tool_choice": {"type": "auto", "disable_parallel_tool_use": True}}
        )
        assert result == "auto"


# ---------------------------------------------------------------------------
# parallel_tool_calls mapping
# ---------------------------------------------------------------------------


class TestParallelToolCalls:
    def test_disable_parallel_with_auto(self):
        body = {
            "model": "claude-3",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert openai_body["parallel_tool_calls"] is False
        assert openai_body["tool_choice"] == "auto"

    def test_disable_parallel_with_any(self):
        body = {
            "model": "claude-3",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": {"type": "any", "disable_parallel_tool_use": True},
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert openai_body["parallel_tool_calls"] is False
        assert openai_body["tool_choice"] == "required"

    def test_disable_parallel_with_specific_tool(self):
        body = {
            "model": "claude-3",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": {"type": "tool", "name": "search", "disable_parallel_tool_use": True},
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert openai_body["parallel_tool_calls"] is False

    def test_parallel_not_disabled_by_default(self):
        body = {
            "model": "claude-3",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": {"type": "auto"},
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert "parallel_tool_calls" not in openai_body

    def test_parallel_not_set_when_false(self):
        body = {
            "model": "claude-3",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": {"type": "auto", "disable_parallel_tool_use": False},
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert "parallel_tool_calls" not in openai_body

    def test_parallel_not_set_without_tool_choice(self):
        body = {
            "model": "claude-3",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert "parallel_tool_calls" not in openai_body

    def test_parallel_not_set_with_none_tool_choice(self):
        body = {
            "model": "claude-3",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": {"type": "none"},
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert "parallel_tool_calls" not in openai_body


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
        assert response["usage"] == {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}

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
        # OpenAI backends strip stop sequences from output, so even when
        # the stop was caused by a sequence the text won't end with it.
        # Default to the first configured stop sequence.
        assert reason == "stop_sequence"
        assert seq == "\n\nHuman:"

    def test_stop_with_sequences_but_no_content(self):
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=["\n\nHuman:"],
            content_text=None,
        )
        # No content to check — default to the first stop sequence
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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient
from unittest.mock import AsyncMock

_integration_app = FastAPI()
_integration_app.include_router(anthropic_compat.anthropic_compatible_routes)


@_integration_app.exception_handler(HTTPException)
async def _test_http_exception_handler(request: Request, exc: HTTPException):
  """Mirror the global handler from main.py for test fidelity."""
  error_type = anthropic_compat.ERROR_TYPE_MAP.get(exc.status_code, "api_error")
  return JSONResponse(
    status_code=exc.status_code,
    content={
      "type": "error",
      "error": {"type": error_type, "message": str(exc.detail)},
    },
  )


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

    def test_missing_auth_returns_401(self):
        client = _make_client(auth_key="sk-secret")
        resp = client.post("/v1/messages", json=_ANTHRO_BODY)
        assert resp.status_code == 401

    def test_missing_auth_has_anthropic_error_format(self):
        client = _make_client(auth_key="sk-secret")
        resp = client.post("/v1/messages", json=_ANTHRO_BODY)
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "authentication_error"
        assert isinstance(body["error"]["message"], str)

    def test_wrong_api_key_returns_401(self):
        client = _make_client(auth_key="sk-secret")
        resp = client.post(
            "/v1/messages", json=_ANTHRO_BODY,
            headers={"x-api-key": "sk-wrong"},
        )
        assert resp.status_code == 401

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
        assert resp.status_code == 401

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
# Deep streaming edge cases
# ---------------------------------------------------------------------------

class TestStreamConverterDeepEdgeCases:
    """Test subtle edge cases in the streaming converter that can occur
    with various real-world backends."""

    @pytest.mark.asyncio
    async def test_chunk_with_both_text_and_tool_calls(self):
        """Some backends send text content AND tool calls in the same chunk.
        Both must be processed: text emitted first, then text block closed,
        then tool block opened."""
        async def response_stream():
            yield (
                'data: {"choices": [{"delta": {"content": "Let me search.", '
                '"tool_calls": [{"index": 0, "id": "call_abc", '
                '"function": {"name": "web_search", "arguments": "{\\"q\\": \\"test\\"}"}}]}}]}\n\n'
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

        # Should have both text and tool_use blocks
        assert "Let me search." in joined
        assert '"type": "tool_use"' in joined

        # Verify event ordering: text block opened, text delta, text block closed,
        # then tool block opened
        types = [e.get("type") for e in parsed]
        assert "content_block_start" in types
        assert "text_delta" in [e.get("delta", {}).get("type") for e in parsed if e.get("type") == "content_block_delta"]

        # Count content_block_start events — should be 2 (text + tool)
        starts = [e for e in parsed if e.get("type") == "content_block_start"]
        assert len(starts) == 2
        assert starts[0]["content_block"]["type"] == "text"
        assert starts[1]["content_block"]["type"] == "tool_use"

        # Both blocks should have content_block_stop
        stops = [e for e in parsed if e.get("type") == "content_block_stop"]
        assert len(stops) == 2

    @pytest.mark.asyncio
    async def test_chunk_with_text_and_multiple_tool_calls(self):
        """A single chunk containing text AND multiple tool calls."""
        async def response_stream():
            yield (
                'data: {"choices": [{"delta": {"content": "Found it.", '
                '"tool_calls": ['
                '{"index": 0, "id": "call_1", "function": {"name": "search", "arguments": "{\\"a\\": 1}"}}, '
                '{"index": 1, "id": "call_2", "function": {"name": "calc", "arguments": "{\\"b\\": 2}"}}'
                ']}}]}\n\n'
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

        # 3 content_block_start events: 1 text + 2 tools
        starts = [e for e in parsed if e.get("type") == "content_block_start"]
        assert len(starts) == 3
        assert starts[0]["content_block"]["type"] == "text"
        assert starts[1]["content_block"]["type"] == "tool_use"
        assert starts[2]["content_block"]["type"] == "tool_use"

        # 3 content_block_stop events
        stops = [e for e in parsed if e.get("type") == "content_block_stop"]
        assert len(stops) == 3

    @pytest.mark.asyncio
    async def test_tool_call_with_empty_name(self):
        """A tool call chunk with name: '' should emit the block with empty name."""
        async def response_stream():
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "call_x", "function": {"name": "", "arguments": "{\\"k\\": \\"v\\"}"}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], '
                '"usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        # Tool block should be emitted (has id) even with empty name
        starts = [e for e in parsed if e.get("type") == "content_block_start"]
        assert len(starts) == 1
        assert starts[0]["content_block"]["type"] == "tool_use"
        assert starts[0]["content_block"]["name"] == ""

    @pytest.mark.asyncio
    async def test_tool_call_with_null_name(self):
        """A tool call chunk with name: null should emit with empty name."""
        async def response_stream():
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "call_y", "function": {"name": null, "arguments": "{}"}}'
                ']}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], '
                '"usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        starts = [e for e in parsed if e.get("type") == "content_block_start"]
        assert len(starts) == 1
        assert starts[0]["content_block"]["name"] == ""

    @pytest.mark.asyncio
    async def test_tool_call_no_function_key(self):
        """A tool call chunk with id but no function key at all."""
        async def response_stream():
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "call_z"}'
                ']}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], '
                '"usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        starts = [e for e in parsed if e.get("type") == "content_block_start"]
        assert len(starts) == 1
        assert starts[0]["content_block"]["name"] == ""
        assert starts[0]["content_block"]["input"] == {}

    @pytest.mark.asyncio
    async def test_each_block_gets_exactly_one_stop_event(self):
        """Verify no block gets zero or two content_block_stop events.
        Tests text + thinking + tool combination."""
        async def response_stream():
            # Thinking
            yield 'data: {"choices": [{"delta": {"reasoning_content": "Let me think..."}}]}\n\n'
            # Text
            yield 'data: {"choices": [{"delta": {"content": "Here is the answer."}}]}\n\n'
            # Two tools
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "call_a", "function": {"name": "search", "arguments": "{}"}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 1, "id": "call_b", "function": {"name": "calc", "arguments": "{}"}}]}}]}\n\n'
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

        starts = [e for e in parsed if e.get("type") == "content_block_start"]
        stops = [e for e in parsed if e.get("type") == "content_block_stop"]

        # 4 blocks: thinking + text + 2 tools
        assert len(starts) == 4
        assert len(stops) == 4

        # Verify each index appears exactly once in stops
        stop_indices = [e["index"] for e in stops]
        assert sorted(stop_indices) == [0, 1, 2, 3]

    @pytest.mark.asyncio
    async def test_finish_reason_only_stream(self):
        """Stream with ONLY a finish_reason chunk and no content at all.
        Should produce valid message envelope with no content blocks."""
        async def response_stream():
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
                '"usage": {"prompt_tokens": 0, "completion_tokens": 0}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        types = [e.get("type") for e in parsed]
        assert "message_start" in types
        assert "message_delta" in types
        assert "message_stop" in types
        # No content blocks at all
        assert "content_block_start" not in types
        assert "content_block_delta" not in types
        assert "content_block_stop" not in types

    @pytest.mark.asyncio
    async def test_empty_text_deltas_skipped(self):
        """Chunks with delta.content: '' should not emit text_delta events."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": ""}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": ""}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": ""}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        # Only one text_delta should be emitted (for "Hello")
        deltas = [
            e for e in parsed
            if e.get("type") == "content_block_delta"
            and e.get("delta", {}).get("type") == "text_delta"
        ]
        assert len(deltas) == 1
        assert deltas[0]["delta"]["text"] == "Hello"

    @pytest.mark.asyncio
    async def test_null_content_deltas_skipped(self):
        """Chunks with delta.content: null should not emit text_delta events."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": null}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": "World"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        deltas = [
            e for e in parsed
            if e.get("type") == "content_block_delta"
            and e.get("delta", {}).get("type") == "text_delta"
        ]
        assert len(deltas) == 1
        assert deltas[0]["delta"]["text"] == "World"

    @pytest.mark.asyncio
    async def test_role_in_delta_ignored(self):
        """Some backends send delta.role: 'assistant' in the first chunk.
        This should be silently ignored."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"role": "assistant"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        # The role chunk should not produce any content blocks
        # Only the "Hi" chunk should produce a text block
        deltas = [
            e for e in parsed
            if e.get("type") == "content_block_delta"
        ]
        assert len(deltas) == 1
        assert deltas[0]["delta"]["text"] == "Hi"

        # "assistant" should not appear in any content
        assert '"role"' not in joined or '"assistant"' in joined  # role appears in message_start
        # No assistant text in content
        for e in parsed:
            if e.get("type") == "content_block_delta":
                assert "assistant" not in str(e.get("delta", {}).get("text", ""))

    @pytest.mark.asyncio
    async def test_role_and_null_content_in_first_chunk(self):
        """Backend sends role + null content in first chunk, then real content later."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"role": "assistant", "content": null}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": "Response"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        # Only one content_block_start for the text
        starts = [e for e in parsed if e.get("type") == "content_block_start"]
        assert len(starts) == 1
        assert starts[0]["content_block"]["type"] == "text"

        # Only one text_delta
        deltas = [
            e for e in parsed
            if e.get("type") == "content_block_delta"
            and e.get("delta", {}).get("type") == "text_delta"
        ]
        assert len(deltas) == 1
        assert deltas[0]["delta"]["text"] == "Response"

    @pytest.mark.asyncio
    async def test_tool_args_before_id(self):
        """Some backends send tool arguments before the id chunk.
        The converter should defer emission until the id arrives and flush
        accumulated arguments."""
        async def response_stream():
            # First chunk: args only, no id
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "function": {"arguments": "{\\"key\\""}}'
                ']}}]}\n\n'
            )
            # Second chunk: more args
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "function": {"arguments": ": \\"val\\"}"}}'
                ']}}]}\n\n'
            )
            # Third chunk: id and name arrive
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "call_late", "function": {"name": "my_tool"}}'
                ']}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], '
                '"usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        # Tool should be emitted when id arrives
        starts = [e for e in parsed if e.get("type") == "content_block_start"]
        assert len(starts) == 1
        assert starts[0]["content_block"]["name"] == "my_tool"

        # Accumulated arguments should be flushed
        deltas = [
            e for e in parsed
            if e.get("type") == "content_block_delta"
            and e.get("delta", {}).get("type") == "input_json_delta"
        ]
        assert len(deltas) == 1
        assert deltas[0]["delta"]["partial_json"] == '{"key": "val"}'

    @pytest.mark.asyncio
    async def test_tool_no_id_is_deferred_then_flushed(self):
        """Tool call chunks with arguments but never an id should be skipped
        in the deferred flush (no id means no block to emit)."""
        async def response_stream():
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "function": {"name": "ghost", "arguments": "{}"}}'
                ']}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
                '"usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        # No tool block should be emitted since there's no id
        starts = [e for e in parsed if e.get("type") == "content_block_start"]
        assert len(starts) == 0
        assert '"type": "tool_use"' not in joined

    @pytest.mark.asyncio
    async def test_interleaved_text_after_tool_reopens_text_block(self):
        """Unlikely but possible: text arrives, then tool, then more text.
        The second text should open a new text block."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "First."}}]}\n\n'
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "call_m", "function": {"name": "search", "arguments": "{}"}}'
                ']}}]}\n\n'
            )
            yield 'data: {"choices": [{"delta": {"content": "Second."}}]}\n\n'
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
                '"usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        # Should have 3 content_block_starts: text, tool, text
        starts = [e for e in parsed if e.get("type") == "content_block_start"]
        assert len(starts) == 3
        assert starts[0]["content_block"]["type"] == "text"
        assert starts[1]["content_block"]["type"] == "tool_use"
        assert starts[2]["content_block"]["type"] == "text"

        # Each block should have exactly one stop
        stops = [e for e in parsed if e.get("type") == "content_block_stop"]
        assert len(stops) == 3

    @pytest.mark.asyncio
    async def test_multiple_consecutive_empty_chunks(self):
        """Multiple chunks with no content, role, or tool_calls.
        Common with keepalive chunks from some backends."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": "Finally"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        # Only one text delta
        deltas = [
            e for e in parsed
            if e.get("type") == "content_block_delta"
        ]
        assert len(deltas) == 1
        assert deltas[0]["delta"]["text"] == "Finally"

    @pytest.mark.asyncio
    async def test_finish_reason_tool_calls_without_tool_blocks(self):
        """Backend sends finish_reason: tool_calls but no actual tool_calls
        in any chunk. Should map to end_turn, not tool_use."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Done"}}]}\n\n'
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], '
                '"usage": {"prompt_tokens": 1, "completion_tokens": 1}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)
        parsed = _parse_sse_events(joined)

        # finish_reason is tool_calls but no visible tool_use, so should be end_turn
        msg_delta = [e for e in parsed if e.get("type") == "message_delta"]
        assert len(msg_delta) == 1
        assert msg_delta[0]["delta"]["stop_reason"] == "end_turn"


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
# Content block index tracking (all scenarios)
# ---------------------------------------------------------------------------

class TestContentBlockIndexTracking:
    """Verify the ``index`` field on content_block_start, content_block_delta,
    and content_block_stop events is correct in every combination of block types."""

    @pytest.mark.asyncio
    async def test_text_only_all_indices_zero(self):
        """Text-only stream: every content_block event uses index 0."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": " world"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))

        block_starts = [e for e in parsed if e["type"] == "content_block_start"]
        assert len(block_starts) == 1
        assert block_starts[0]["index"] == 0
        assert block_starts[0]["content_block"]["type"] == "text"

        block_deltas = [e for e in parsed if e["type"] == "content_block_delta"]
        assert len(block_deltas) == 2
        assert all(d["index"] == 0 for d in block_deltas)

        block_stops = [e for e in parsed if e["type"] == "content_block_stop"]
        assert len(block_stops) == 1
        assert block_stops[0]["index"] == 0

    @pytest.mark.asyncio
    async def test_thinking_then_text_indices(self):
        """Thinking + text: thinking at index 0, text at index 1."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"reasoning_content": "Let me think"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": "Answer."}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))

        block_starts = [e for e in parsed if e["type"] == "content_block_start"]
        assert len(block_starts) == 2
        assert block_starts[0]["index"] == 0
        assert block_starts[0]["content_block"]["type"] == "thinking"
        assert block_starts[1]["index"] == 1
        assert block_starts[1]["content_block"]["type"] == "text"

        thinking_deltas = [e for e in parsed if e["type"] == "content_block_delta" and e["delta"]["type"] == "thinking_delta"]
        assert all(d["index"] == 0 for d in thinking_deltas)

        text_deltas = [e for e in parsed if e["type"] == "content_block_delta" and e["delta"]["type"] == "text_delta"]
        assert all(d["index"] == 1 for d in text_deltas)

        block_stops = [e for e in parsed if e["type"] == "content_block_stop"]
        stop_indices = [s["index"] for s in block_stops]
        assert 0 in stop_indices
        assert 1 in stop_indices

    @pytest.mark.asyncio
    async def test_text_then_two_tool_calls_indices(self):
        """Text + 2 tool calls: text at 0, tools at 1 and 2."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "I will help."}}]}\n\n'
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "toolu_a", "function": '
                '{"name": "search", "arguments": "{\\"q\\": \\"x\\"}"}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 1, "id": "toolu_b", "function": '
                '{"name": "calc", "arguments": "{\\"n\\": 1}"}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], '
                '"usage": {"prompt_tokens": 5, "completion_tokens": 10}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))

        block_starts = [e for e in parsed if e["type"] == "content_block_start"]
        assert len(block_starts) == 3

        # text at index 0
        assert block_starts[0]["index"] == 0
        assert block_starts[0]["content_block"]["type"] == "text"

        # first tool at index 1
        assert block_starts[1]["index"] == 1
        assert block_starts[1]["content_block"]["type"] == "tool_use"
        assert block_starts[1]["content_block"]["name"] == "search"

        # second tool at index 2
        assert block_starts[2]["index"] == 2
        assert block_starts[2]["content_block"]["type"] == "tool_use"
        assert block_starts[2]["content_block"]["name"] == "calc"

        # text deltas at index 0
        text_deltas = [e for e in parsed if e["type"] == "content_block_delta" and e["delta"]["type"] == "text_delta"]
        assert all(d["index"] == 0 for d in text_deltas)

        # tool deltas at their respective indices
        tool_deltas = [e for e in parsed if e["type"] == "content_block_delta" and e["delta"]["type"] == "input_json_delta"]
        assert len(tool_deltas) == 2
        assert tool_deltas[0]["index"] == 1
        assert tool_deltas[1]["index"] == 2

        # content_block_stop for each
        block_stops = [e for e in parsed if e["type"] == "content_block_stop"]
        stop_indices = sorted([s["index"] for s in block_stops])
        assert stop_indices == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_thinking_text_tool_indices(self):
        """Thinking + text + tool: thinking 0, text 1, tool 2."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"reasoning_content": "Reasoning..."}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": "Here is the result."}}]}\n\n'
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "toolu_c", "function": '
                '{"name": "run", "arguments": "{\\"cmd\\": \\"ls\\"}"}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], '
                '"usage": {"prompt_tokens": 10, "completion_tokens": 20}}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))

        block_starts = [e for e in parsed if e["type"] == "content_block_start"]
        assert len(block_starts) == 3

        # thinking at index 0
        assert block_starts[0]["index"] == 0
        assert block_starts[0]["content_block"]["type"] == "thinking"

        # text at index 1
        assert block_starts[1]["index"] == 1
        assert block_starts[1]["content_block"]["type"] == "text"

        # tool at index 2
        assert block_starts[2]["index"] == 2
        assert block_starts[2]["content_block"]["type"] == "tool_use"
        assert block_starts[2]["content_block"]["name"] == "run"

        # Verify deltas reference correct indices
        thinking_deltas = [e for e in parsed if e["type"] == "content_block_delta" and e["delta"]["type"] == "thinking_delta"]
        assert all(d["index"] == 0 for d in thinking_deltas)

        text_deltas = [e for e in parsed if e["type"] == "content_block_delta" and e["delta"]["type"] == "text_delta"]
        assert all(d["index"] == 1 for d in text_deltas)

        tool_deltas = [e for e in parsed if e["type"] == "content_block_delta" and e["delta"]["type"] == "input_json_delta"]
        assert all(d["index"] == 2 for d in tool_deltas)

        # All three blocks stopped
        block_stops = [e for e in parsed if e["type"] == "content_block_stop"]
        stop_indices = sorted([s["index"] for s in block_stops])
        assert stop_indices == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_tool_only_indices(self):
        """Tool-only stream (no text): tool at index 0."""
        async def response_stream():
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "toolu_d", "function": '
                '{"name": "get", "arguments": ""}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "function": '
                '{"arguments": "{\\"key\\": \\"val\\"}"}}]}}]}\n\n'
            )
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}\n\n'
            )

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))

        block_starts = [e for e in parsed if e["type"] == "content_block_start"]
        assert len(block_starts) == 1
        assert block_starts[0]["index"] == 0
        assert block_starts[0]["content_block"]["type"] == "tool_use"

        block_deltas = [e for e in parsed if e["type"] == "content_block_delta"]
        # First delta is the initial args (empty string buffered, then emitted with start),
        # second delta is the follow-up args
        for d in block_deltas:
            assert d["index"] == 0

        block_stops = [e for e in parsed if e["type"] == "content_block_stop"]
        assert len(block_stops) == 1
        assert block_stops[0]["index"] == 0

    @pytest.mark.asyncio
    async def test_three_tool_calls_indices(self):
        """Three parallel tool calls: indices 0, 1, 2."""
        async def response_stream():
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "toolu_1", "function": {"name": "a", "arguments": "{}"}}, '
                '{"index": 1, "id": "toolu_2", "function": {"name": "b", "arguments": "{}"}}, '
                '{"index": 2, "id": "toolu_3", "function": {"name": "c", "arguments": "{}"}}]}}]}\n\n'
            )
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))

        block_starts = [e for e in parsed if e["type"] == "content_block_start"]
        assert len(block_starts) == 3
        assert block_starts[0]["index"] == 0
        assert block_starts[1]["index"] == 1
        assert block_starts[2]["index"] == 2

        block_stops = [e for e in parsed if e["type"] == "content_block_stop"]
        stop_indices = sorted([s["index"] for s in block_stops])
        assert stop_indices == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_interleaved_tool_argument_deltas_use_correct_index(self):
        """When two tool calls receive interleaved argument chunks,
        each delta references the correct block index."""
        async def response_stream():
            # First tool announced
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "toolu_x", "function": {"name": "foo", "arguments": ""}}]}}]}\n\n'
            )
            # Second tool announced
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 1, "id": "toolu_y", "function": {"name": "bar", "arguments": ""}}]}}]}\n\n'
            )
            # Args for first tool
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "function": {"arguments": "{\\"a\\":"}}]}}]}\n\n'
            )
            # Args for second tool
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 1, "function": {"arguments": "{\\"b\\":"}}]}}]}\n\n'
            )
            # More args for first tool
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "function": {"arguments": " 1}"}}]}}]}\n\n'
            )
            # More args for second tool
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 1, "function": {"arguments": " 2}"}}]}}]}\n\n'
            )
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))

        block_starts = [e for e in parsed if e["type"] == "content_block_start"]
        assert len(block_starts) == 2
        # Tool blocks at indices 0 and 1
        assert block_starts[0]["index"] == 0
        assert block_starts[0]["content_block"]["name"] == "foo"
        assert block_starts[1]["index"] == 1
        assert block_starts[1]["content_block"]["name"] == "bar"

        # Verify each delta references the correct block index
        tool_deltas = [e for e in parsed if e["type"] == "content_block_delta" and e["delta"]["type"] == "input_json_delta"]
        # We expect 4 deltas: 2 for foo (index 0) and 2 for bar (index 1)
        foo_deltas = [d for d in tool_deltas if d["index"] == 0]
        bar_deltas = [d for d in tool_deltas if d["index"] == 1]
        assert len(foo_deltas) == 2
        assert len(bar_deltas) == 2

    @pytest.mark.asyncio
    async def test_thinking_then_two_tools_indices(self):
        """Thinking + 2 tool calls (no text): thinking 0, tools 1 and 2."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"reasoning_content": "Planning..."}}]}\n\n'
            yield (
                'data: {"choices": [{"delta": {"tool_calls": ['
                '{"index": 0, "id": "toolu_p", "function": {"name": "fetch", "arguments": "{\\"url\\": \\"x\\"}"}}, '
                '{"index": 1, "id": "toolu_q", "function": {"name": "parse", "arguments": "{\\"fmt\\": \\"json\\"}"}}]}}]}\n\n'
            )
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))

        block_starts = [e for e in parsed if e["type"] == "content_block_start"]
        assert len(block_starts) == 3

        # thinking at 0
        assert block_starts[0]["index"] == 0
        assert block_starts[0]["content_block"]["type"] == "thinking"

        # tools at 1 and 2
        assert block_starts[1]["index"] == 1
        assert block_starts[1]["content_block"]["type"] == "tool_use"
        assert block_starts[1]["content_block"]["name"] == "fetch"
        assert block_starts[2]["index"] == 2
        assert block_starts[2]["content_block"]["type"] == "tool_use"
        assert block_starts[2]["content_block"]["name"] == "parse"

        # stops at 0, 1, 2
        block_stops = [e for e in parsed if e["type"] == "content_block_stop"]
        stop_indices = sorted([s["index"] for s in block_stops])
        assert stop_indices == [0, 1, 2]


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
# top_k passthrough
# ---------------------------------------------------------------------------

class TestConvertParamsTopK:
    def test_top_k_passed_through(self):
        body = {"max_tokens": 256, "top_k": 40}
        params = anthropic_compat._convert_params(body)
        assert params["top_k"] == 40
        assert params["max_tokens"] == 256

    def test_top_k_absent_not_included(self):
        body = {"max_tokens": 256}
        params = anthropic_compat._convert_params(body)
        assert "top_k" not in params

    def test_top_k_with_temperature_and_top_p(self):
        body = {"max_tokens": 256, "temperature": 0.8, "top_p": 0.95, "top_k": 50}
        params = anthropic_compat._convert_params(body)
        assert params["top_k"] == 50
        assert params["temperature"] == 0.8
        assert params["top_p"] == 0.95

    def test_top_k_zero(self):
        """top_k=0 is a valid value (some backends treat it as disabled)."""
        body = {"max_tokens": 256, "top_k": 0}
        params = anthropic_compat._convert_params(body)
        # 0 is falsy but present — the check is "in body", not truthiness
        assert "top_k" in params
        assert params["top_k"] == 0

    def test_top_k_in_build_openai_body(self):
        """Verify top_k flows through _build_openai_body end-to-end."""
        body = {
            "model": "test-model",
            "max_tokens": 128,
            "top_k": 40,
            "messages": [{"role": "user", "content": "hello"}],
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert openai_body["top_k"] == 40


class TestConvertParamsTopKIntegration:
    """Verify top_k reaches the OpenAI body in the route handler."""

    def setup_method(self):
        import config as _cfg
        _cfg.BOOST_AUTH = []

    def test_top_k_forwarded_to_backend(self):
        fake_llm = _FakeLLM(
            consume_result=_fake_openai_result(),
            stream_chunks=[],
        )

        captured_body = {}

        def capture_resolve(body):
            captured_body.update(body)
            return {}

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(side_effect=capture_resolve)
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            client = TestClient(_integration_app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json={
                **_ANTHRO_BODY,
                "top_k": 40,
            })

        assert resp.status_code == 200
        assert captured_body.get("top_k") == 40


# ---------------------------------------------------------------------------
# cache_control stripping verification
# ---------------------------------------------------------------------------

class TestCacheControlStripped:
    """Verify cache_control directives on content blocks are stripped during conversion."""

    def test_system_cache_control_stripped(self):
        """cache_control on system text blocks is not forwarded."""
        body = {
            "model": "m",
            "max_tokens": 64,
            "system": [
                {"type": "text", "text": "System prompt.", "cache_control": {"type": "ephemeral"}},
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }
        openai_body = anthropic_compat._build_openai_body(body)
        system_msg = openai_body["messages"][0]
        assert system_msg["role"] == "system"
        assert system_msg["content"] == "System prompt."
        assert "cache_control" not in system_msg

    def test_user_text_cache_control_stripped(self):
        """cache_control on user text blocks is not forwarded."""
        body = {
            "model": "m",
            "max_tokens": 64,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Hello", "cache_control": {"type": "ephemeral"}},
                ],
            }],
        }
        openai_body = anthropic_compat._build_openai_body(body)
        user_msg = openai_body["messages"][0]
        assert user_msg["role"] == "user"
        assert user_msg["content"] == "Hello"
        assert "cache_control" not in str(user_msg)

    def test_multi_system_blocks_with_cache_control(self):
        """Multiple system blocks, some with cache_control, are joined correctly."""
        body = {
            "model": "m",
            "max_tokens": 64,
            "system": [
                {"type": "text", "text": "Part 1"},
                {"type": "text", "text": "Part 2", "cache_control": {"type": "ephemeral"}},
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }
        openai_body = anthropic_compat._build_openai_body(body)
        system_msg = openai_body["messages"][0]
        assert system_msg["content"] == "Part 1\nPart 2"

    def test_tool_result_cache_control_stripped(self):
        """cache_control on tool_result content blocks is not forwarded."""
        body = {
            "model": "m",
            "max_tokens": 64,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_abc",
                        "content": [
                            {
                                "type": "text",
                                "text": "Result text",
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                ],
            }],
        }
        openai_body = anthropic_compat._build_openai_body(body)
        tool_msg = openai_body["messages"][0]
        assert tool_msg["role"] == "tool"
        assert tool_msg["content"] == "Result text"
        assert "cache_control" not in str(tool_msg)


# ---------------------------------------------------------------------------
# Verify temperature, top_p are already handled
# ---------------------------------------------------------------------------

class TestConvertParamsExistingParams:
    """Confirm that temperature and top_p are correctly forwarded."""

    def test_temperature_forwarded(self):
        body = {"max_tokens": 256, "temperature": 0.5}
        params = anthropic_compat._convert_params(body)
        assert params["temperature"] == 0.5

    def test_temperature_zero(self):
        """temperature=0 is valid and should be forwarded."""
        body = {"max_tokens": 256, "temperature": 0}
        params = anthropic_compat._convert_params(body)
        assert "temperature" in params
        assert params["temperature"] == 0

    def test_top_p_forwarded(self):
        body = {"max_tokens": 256, "top_p": 0.9}
        params = anthropic_compat._convert_params(body)
        assert params["top_p"] == 0.9

    def test_top_p_zero(self):
        body = {"max_tokens": 256, "top_p": 0}
        params = anthropic_compat._convert_params(body)
        assert "top_p" in params
        assert params["top_p"] == 0

    def test_metadata_not_forwarded(self):
        """metadata is silently accepted but not passed to the OpenAI body."""
        body = {
            "max_tokens": 256,
            "metadata": {"user_id": "user-123"},
        }
        params = anthropic_compat._convert_params(body)
        assert "metadata" not in params


# ---------------------------------------------------------------------------
# max_tokens / max_completion_tokens handling
# ---------------------------------------------------------------------------


class TestMaxTokensHandling:
    """Verify max_tokens mapping from Anthropic to OpenAI format."""

    def test_max_tokens_maps_to_openai_max_tokens(self):
        """Standard max_tokens should map to OpenAI max_tokens (widely supported)."""
        body = {"max_tokens": 1024}
        params = anthropic_compat._convert_params(body)
        assert params["max_tokens"] == 1024
        assert "max_completion_tokens" not in params

    def test_max_tokens_in_full_body(self):
        """max_tokens flows through _build_openai_body correctly."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": "hi"}],
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert openai_body["max_tokens"] == 2048
        assert "max_completion_tokens" not in openai_body

    def test_thinking_uses_max_completion_tokens(self):
        """When thinking is enabled, max_completion_tokens is used instead."""
        body = {
            "max_tokens": 1024,
            "thinking": {"type": "enabled", "budget_tokens": 4096},
        }
        params = anthropic_compat._convert_params(body)
        assert "max_tokens" not in params
        assert params["max_completion_tokens"] == 5120  # 4096 + 1024

    def test_thinking_max_completion_tokens_in_full_body(self):
        """Thinking path flows through _build_openai_body correctly."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 512,
            "thinking": {"type": "enabled", "budget_tokens": 2048},
            "messages": [{"role": "user", "content": "hi"}],
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert "max_tokens" not in openai_body
        assert openai_body["max_completion_tokens"] == 2560

    def test_max_tokens_with_temperature_zero(self):
        """max_tokens and temperature=0 together are correctly forwarded."""
        body = {"max_tokens": 256, "temperature": 0}
        params = anthropic_compat._convert_params(body)
        assert params["max_tokens"] == 256
        assert params["temperature"] == 0

    def test_max_tokens_not_set_when_zero(self):
        """max_tokens=0 is not a valid Anthropic value; should not be forwarded."""
        body = {"max_tokens": 0}
        params = anthropic_compat._convert_params(body)
        assert "max_tokens" not in params


# ---------------------------------------------------------------------------
# Tool ID Normalization
# ---------------------------------------------------------------------------


class TestToolIdNormalization:
    """Verify that compat_utils.to_anthropic_tool_id and to_openai_tool_id
    correctly re-prefix tool IDs for their respective API surfaces."""

    def test_to_anthropic_already_prefixed(self):
        from compat_utils import to_anthropic_tool_id
        assert to_anthropic_tool_id("toolu_abc123") == "toolu_abc123"

    def test_to_anthropic_from_call_prefix(self):
        from compat_utils import to_anthropic_tool_id
        assert to_anthropic_tool_id("call_abc123") == "toolu_abc123"

    def test_to_anthropic_from_chatcmpl_prefix(self):
        from compat_utils import to_anthropic_tool_id
        assert to_anthropic_tool_id("chatcmpl-abc123") == "toolu_abc123"

    def test_to_anthropic_bare_id(self):
        from compat_utils import to_anthropic_tool_id
        assert to_anthropic_tool_id("abc123") == "toolu_abc123"

    def test_to_anthropic_empty(self):
        from compat_utils import to_anthropic_tool_id
        assert to_anthropic_tool_id("") == ""

    def test_to_openai_already_prefixed(self):
        from compat_utils import to_openai_tool_id
        assert to_openai_tool_id("call_abc123") == "call_abc123"

    def test_to_openai_from_toolu_prefix(self):
        from compat_utils import to_openai_tool_id
        assert to_openai_tool_id("toolu_abc123") == "call_abc123"

    def test_to_openai_from_chatcmpl_prefix(self):
        from compat_utils import to_openai_tool_id
        assert to_openai_tool_id("chatcmpl-abc123") == "call_abc123"

    def test_to_openai_bare_id(self):
        from compat_utils import to_openai_tool_id
        assert to_openai_tool_id("abc123") == "call_abc123"

    def test_to_openai_empty(self):
        from compat_utils import to_openai_tool_id
        assert to_openai_tool_id("") == ""


class TestAnthropicToolIdNormalizationInResponses:
    """Verify tool IDs are normalized to toolu_ prefix in Anthropic responses."""

    def test_build_content_blocks_normalizes_call_prefix(self):
        """Backend returns call_-prefixed IDs; should become toolu_ in Anthropic response."""
        openai_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_abc123",
                        "function": {"name": "search", "arguments": '{"q": "test"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {},
        }
        blocks = anthropic_compat._build_content_blocks(openai_result)
        tool_block = [b for b in blocks if b["type"] == "tool_use"][0]
        assert tool_block["id"] == "toolu_abc123"

    def test_build_content_blocks_preserves_toolu_prefix(self):
        """Backend returns toolu_-prefixed IDs; should remain unchanged."""
        openai_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "toolu_xyz789",
                        "function": {"name": "fetch", "arguments": '{}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {},
        }
        blocks = anthropic_compat._build_content_blocks(openai_result)
        tool_block = [b for b in blocks if b["type"] == "tool_use"][0]
        assert tool_block["id"] == "toolu_xyz789"

    def test_build_content_blocks_normalizes_chatcmpl_prefix(self):
        """Backend returns chatcmpl-prefixed IDs; should become toolu_."""
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
            "usage": {},
        }
        blocks = anthropic_compat._build_content_blocks(openai_result)
        tool_block = [b for b in blocks if b["type"] == "tool_use"][0]
        assert tool_block["id"] == "toolu_abc"

    def test_build_anthropic_response_tool_ids_normalized(self):
        """Full response builder should normalize tool IDs."""
        openai_result = {
            "choices": [{
                "message": {
                    "content": "Calling tool",
                    "tool_calls": [{
                        "id": "call_test999",
                        "function": {"name": "search", "arguments": '{"q": "hello"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        response = anthropic_compat._build_anthropic_response(openai_result, "claude-test")
        tool_blocks = [b for b in response["content"] if b["type"] == "tool_use"]
        assert len(tool_blocks) == 1
        assert tool_blocks[0]["id"] == "toolu_test999"

    def test_build_content_blocks_missing_id_generates_toolu(self):
        """Tool call with no id should generate a toolu_-prefixed ID."""
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
            "usage": {},
        }
        blocks = anthropic_compat._build_content_blocks(openai_result)
        tool_block = [b for b in blocks if b["type"] == "tool_use"][0]
        assert tool_block["id"].startswith("toolu_")


class TestAnthropicToolIdNormalizationInRequests:
    """Verify tool IDs are normalized to call_ prefix when converting Anthropic
    requests to OpenAI format for the backend."""

    def test_tool_result_toolu_id_normalized_to_call(self):
        """tool_result with toolu_ ID should become call_ in the OpenAI body."""
        body = {
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "toolu_abc123",
                    "content": "result",
                }],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert msgs[0]["tool_call_id"] == "call_abc123"

    def test_tool_result_call_id_passed_through(self):
        """tool_result with call_ ID should remain unchanged (already correct)."""
        body = {
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "call_xyz",
                    "content": "result",
                }],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert msgs[0]["tool_call_id"] == "call_xyz"

    def test_assistant_tool_use_id_normalized_to_call(self):
        """tool_use in assistant message should have id normalized to call_ for backend."""
        body = {
            "messages": [{
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": "toolu_def456",
                    "name": "search",
                    "input": {"q": "test"},
                }],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert msgs[0]["tool_calls"][0]["id"] == "call_def456"

    def test_round_trip_ids_stay_consistent(self):
        """Full round-trip: backend sends call_ -> response has toolu_ -> client sends
        toolu_ in tool_result -> we convert back to call_ for backend."""
        # Step 1: Backend result with call_ prefix
        openai_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_round1",
                        "function": {"name": "search", "arguments": '{}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {},
        }
        # Step 2: Build Anthropic response -> should have toolu_ prefix
        response = anthropic_compat._build_anthropic_response(openai_result, "claude-test")
        tool_id = response["content"][0]["id"]
        assert tool_id == "toolu_round1"

        # Step 3: Client sends back tool_result with the toolu_ ID
        body = {
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": "search results",
                }],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        # Step 4: Should be normalized back to call_ for the backend
        assert msgs[0]["tool_call_id"] == "call_round1"


class TestAnthropicToolIdNormalizationInStreaming:
    """Verify tool IDs are normalized to toolu_ in Anthropic streaming responses."""

    @pytest.mark.asyncio
    async def test_stream_normalizes_call_prefix_to_toolu(self):
        """Streaming tool call with call_ prefix should emit toolu_ in content_block_start."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_stream1","function":{"name":"search","arguments":""}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"q\\":\\"test\\"}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":5,"completion_tokens":10,"total_tokens":15}}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in anthropic_compat._anthropic_stream_converter(
            mock_stream(), "claude-test"
        ):
            events.append(event)

        # Find content_block_start with tool_use
        for raw in events:
            data = json.loads(raw.split("data: ", 1)[1]) if "data: " in raw else None
            if data and data.get("type") == "content_block_start":
                block = data.get("content_block", {})
                if block.get("type") == "tool_use":
                    assert block["id"] == "toolu_stream1"
                    return
        pytest.fail("No tool_use content_block_start found in stream events")

    @pytest.mark.asyncio
    async def test_stream_preserves_toolu_prefix(self):
        """Streaming tool call with toolu_ prefix should remain unchanged."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"toolu_existing","function":{"name":"fn","arguments":"{}"}}]},"index":0}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n'
            yield 'data: [DONE]\n\n'

        events = []
        async for event in anthropic_compat._anthropic_stream_converter(
            mock_stream(), "claude-test"
        ):
            events.append(event)

        for raw in events:
            data = json.loads(raw.split("data: ", 1)[1]) if "data: " in raw else None
            if data and data.get("type") == "content_block_start":
                block = data.get("content_block", {})
                if block.get("type") == "tool_use":
                    assert block["id"] == "toolu_existing"
                    return
        pytest.fail("No tool_use content_block_start found in stream events")


# ---------------------------------------------------------------------------
# SSE parsing helper
# ---------------------------------------------------------------------------

def _parse_sse_events(raw_text):
    """Parse raw SSE text into a list of data payloads (dicts).

    Skips non-data events such as ``event: ping`` whose payload has no
    ``type`` field — these are connection keep-alive signals, not
    Anthropic protocol events.
    """
    events = []
    for block in raw_text.strip().split("\n\n"):
        data_line = None
        for line in block.strip().split("\n"):
            if line.startswith("data: "):
                data_line = line[6:]
        if data_line:
            try:
                parsed = json.loads(data_line)
            except json.JSONDecodeError:
                continue
            # Skip ping and other non-protocol events (no "type" key)
            if isinstance(parsed, dict) and "type" not in parsed:
                continue
            events.append(parsed)
    return events


class TestCacheUsageFields:
    """Verify cache_creation_input_tokens and cache_read_input_tokens are present in all usage objects."""

    def test_non_streaming_response_has_cache_fields(self):
        openai_result = {
            "choices": [
                {
                    "message": {"content": "Hello", "role": "assistant"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        response = anthropic_compat._build_anthropic_response(openai_result, "claude-test")
        assert response["usage"]["cache_creation_input_tokens"] == 0
        assert response["usage"]["cache_read_input_tokens"] == 0

    def test_non_streaming_response_cache_fields_are_zero(self):
        """Cache fields should always be 0 since the compat layer does not support prompt caching."""
        openai_result = {
            "choices": [
                {
                    "message": {"content": "Hi", "role": "assistant"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
        response = anthropic_compat._build_anthropic_response(openai_result, "test-model")
        usage = response["usage"]
        assert usage["input_tokens"] == 100
        assert usage["output_tokens"] == 50
        assert usage["cache_creation_input_tokens"] == 0
        assert usage["cache_read_input_tokens"] == 0

    @pytest.mark.asyncio
    async def test_stream_message_start_has_cache_fields(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "X"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)
        msg_start = parsed[0]
        assert msg_start["type"] == "message_start"
        usage = msg_start["message"]["usage"]
        assert usage["cache_creation_input_tokens"] == 0
        assert usage["cache_read_input_tokens"] == 0

    @pytest.mark.asyncio
    async def test_stream_message_delta_has_cache_fields(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "X"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 42, "completion_tokens": 7}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        raw = "".join(events)
        parsed = _parse_sse_events(raw)
        msg_delta = [e for e in parsed if e.get("type") == "message_delta"][0]
        usage = msg_delta["usage"]
        assert usage["cache_creation_input_tokens"] == 0
        assert usage["cache_read_input_tokens"] == 0

    def test_non_streaming_integration_has_cache_fields(self):
        """Verify cache fields propagate through the full non-streaming integration path."""
        consume_result = _fake_openai_result(content="Response text", prompt_tokens=20, completion_tokens=10)
        fake_llm = _FakeLLM(consume_result=consume_result)

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
        assert body["usage"]["cache_creation_input_tokens"] == 0
        assert body["usage"]["cache_read_input_tokens"] == 0


# ---------------------------------------------------------------------------
# Beta flags: _parse_beta_flags
# ---------------------------------------------------------------------------

class TestParseBetaFlags:
    def test_returns_empty_list_when_no_header(self):
        request = make_request({})
        flags = anthropic_compat._parse_beta_flags(request)
        assert flags == []

    def test_parses_single_flag(self):
        request = make_request({"anthropic-beta": "prompt-caching-2024-07-31"})
        flags = anthropic_compat._parse_beta_flags(request)
        assert flags == ["prompt-caching-2024-07-31"]

    def test_parses_multiple_comma_separated_flags(self):
        request = make_request({
            "anthropic-beta": "max-tokens-3-5-sonnet-2024-07-15,prompt-caching-2024-07-31"
        })
        flags = anthropic_compat._parse_beta_flags(request)
        assert flags == ["max-tokens-3-5-sonnet-2024-07-15", "prompt-caching-2024-07-31"]

    def test_strips_whitespace_around_flags(self):
        request = make_request({
            "anthropic-beta": " flag-a , flag-b , flag-c "
        })
        flags = anthropic_compat._parse_beta_flags(request)
        assert flags == ["flag-a", "flag-b", "flag-c"]

    def test_ignores_empty_segments(self):
        request = make_request({"anthropic-beta": "flag-a,,flag-b,"})
        flags = anthropic_compat._parse_beta_flags(request)
        assert flags == ["flag-a", "flag-b"]

    def test_empty_string_returns_empty_list(self):
        request = make_request({"anthropic-beta": ""})
        flags = anthropic_compat._parse_beta_flags(request)
        assert flags == []


class TestBetaFlagsIntegration:
    """Verify that requests with anthropic-beta header are accepted."""

    def test_messages_accepts_beta_header(self):
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

            client = _make_client()
            resp = client.post(
                "/v1/messages", json=_ANTHRO_BODY,
                headers={
                    "authorization": "Bearer test-key",
                    "anthropic-beta": "max-tokens-3-5-sonnet-2024-07-15,prompt-caching-2024-07-31",
                },
            )
            assert resp.status_code == 200

    def test_count_tokens_accepts_beta_header(self):
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

            client = _make_client()
            resp = client.post(
                "/v1/messages/count_tokens", json=_ANTHRO_BODY,
                headers={
                    "authorization": "Bearer test-key",
                    "anthropic-beta": "prompt-caching-2024-07-31",
                },
            )
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# System prompt edge cases
# ---------------------------------------------------------------------------

class TestSystemPromptEdgeCases:
    """Verify system field handling for edge cases not covered elsewhere."""

    def test_empty_string_system_produces_no_message(self):
        """system: '' is falsy and should not produce a system message."""
        body = {
            "system": "",
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_empty_list_system_produces_no_message(self):
        """system: [] is falsy and should not produce a system message."""
        body = {
            "system": [],
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_whitespace_only_string_system_is_preserved(self):
        """Whitespace-only system string is truthy and should be passed through."""
        body = {
            "system": "   ",
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": "   "}

    def test_system_list_with_only_non_text_blocks(self):
        """System array containing only non-text blocks should not produce a system message."""
        body = {
            "system": [
                {"type": "image", "source": {"data": "abc"}},
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_system_list_with_mixed_text_and_non_text_blocks(self):
        """Non-text blocks in the system array are silently dropped."""
        body = {
            "system": [
                {"type": "text", "text": "Important context."},
                {"type": "image", "source": {"data": "abc"}},
                {"type": "text", "text": "More context."},
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": "Important context.\nMore context."}

    def test_system_text_block_missing_text_key(self):
        """A text block without a 'text' key should not crash; defaults to empty string."""
        body = {
            "system": [
                {"type": "text"},  # missing 'text' key
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        # text_parts will be [""], which is truthy, so a system message with "" is created
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": ""}

    def test_system_list_with_cache_control_only_blocks(self):
        """System array with cache_control but valid text should work; cache_control stripped."""
        body = {
            "system": [
                {"type": "text", "text": "Cached.", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "Also cached.", "cache_control": {"type": "ephemeral"}},
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 2
        system_msg = msgs[0]
        assert system_msg["content"] == "Cached.\nAlso cached."
        assert "cache_control" not in system_msg
        assert "cache_control" not in str(system_msg)

    def test_system_absent_produces_no_system_message(self):
        """When 'system' key is entirely absent, no system message is produced."""
        body = {
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_system_none_produces_no_system_message(self):
        """Explicit system: null should be treated the same as absent."""
        body = {
            "system": None,
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_user_text_block_missing_text_key(self):
        """A user text block without a 'text' key should not crash; defaults to empty string."""
        body = {
            "messages": [{
                "role": "user",
                "content": [{"type": "text"}],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        assert msgs[0] == {"role": "user", "content": ""}

    def test_system_with_very_long_text(self):
        """Very long system text should not be truncated."""
        long_text = "x" * 100_000
        body = {
            "system": long_text,
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert msgs[0]["content"] == long_text
        assert len(msgs[0]["content"]) == 100_000

    def test_system_array_with_very_long_text_blocks(self):
        """Very long system array text should not be truncated."""
        long_text = "y" * 50_000
        body = {
            "system": [
                {"type": "text", "text": long_text},
                {"type": "text", "text": long_text},
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert msgs[0]["content"] == f"{long_text}\n{long_text}"
        assert len(msgs[0]["content"]) == 100_001  # 50k + newline + 50k

    def test_system_array_plain_strings_ignored(self):
        """Plain strings in the system array (invalid format) are silently ignored."""
        body = {
            "system": ["This is not a valid block"],
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        # The string is not a dict, so isinstance(block, dict) fails -> filtered out
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_system_array_empty_text_blocks_joined(self):
        """Multiple empty text blocks should produce a system message with just newlines."""
        body = {
            "system": [
                {"type": "text", "text": ""},
                {"type": "text", "text": ""},
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": "\n"}


# ---------------------------------------------------------------------------
# Image and document content block handling
# ---------------------------------------------------------------------------


class TestImageAndDocumentBlocks:
    """Test image and document content block handling in _convert_user_message."""

    def test_base64_image_default_media_type(self):
        """Base64 image without explicit media_type defaults to image/png."""
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "data": "iVBOR"}},
                ],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        content = msgs[0]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "image_url"
        assert content[0]["image_url"]["url"] == "data:image/png;base64,iVBOR"

    def test_base64_image_with_media_type(self):
        """Base64 image with explicit media_type uses that type."""
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/webp",
                            "data": "WEBPDATA",
                        },
                    },
                ],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        content = msgs[0]["content"]
        assert content[0]["image_url"]["url"] == "data:image/webp;base64,WEBPDATA"

    def test_url_image_source(self):
        """URL-based image source should map to image_url with the URL directly."""
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": "https://example.com/photo.jpg",
                        },
                    },
                ],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        content = msgs[0]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "image_url"
        assert content[0]["image_url"]["url"] == "https://example.com/photo.jpg"

    def test_url_image_with_text(self):
        """URL image mixed with text produces multi-part content."""
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": "https://cdn.example.com/cat.png",
                        },
                    },
                ],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert len(msgs) == 1
        content = msgs[0]["content"]
        assert content[0] == {"type": "text", "text": "What is this?"}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == "https://cdn.example.com/cat.png"

    def test_image_source_type_defaults_to_base64(self):
        """When source.type is missing, defaults to base64 handling."""
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "media_type": "image/gif",
                            "data": "R0lGOD",
                        },
                    },
                ],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        content = msgs[0]["content"]
        assert content[0]["image_url"]["url"] == "data:image/gif;base64,R0lGOD"

    def test_multiple_images(self):
        """Multiple image blocks should all be converted."""
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": "img1"},
                    },
                    {
                        "type": "image",
                        "source": {"type": "url", "url": "https://example.com/img2.png"},
                    },
                ],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        content = msgs[0]["content"]
        assert len(content) == 2
        assert content[0]["image_url"]["url"] == "data:image/jpeg;base64,img1"
        assert content[1]["image_url"]["url"] == "https://example.com/img2.png"

    def test_image_with_empty_source(self):
        """Image block with empty source should not crash."""
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {}},
                ],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        content = msgs[0]["content"]
        # Defaults to base64 path with empty data
        assert content[0]["type"] == "image_url"
        assert content[0]["image_url"]["url"] == "data:image/png;base64,"

    def test_document_base64_pdf(self):
        """PDF document block should produce a text placeholder."""
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Summarize this PDF."},
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": "JVBERi0...",
                        },
                    },
                ],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        content = msgs[0]["content"]
        assert len(content) == 2
        assert content[0] == {"type": "text", "text": "Summarize this PDF."}
        assert content[1] == {"type": "text", "text": "[Document: application/pdf]"}

    def test_document_url(self):
        """Document URL source should produce a text placeholder with the URL."""
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "url",
                            "url": "https://example.com/report.pdf",
                        },
                    },
                ],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        # Single text part collapses to string content
        assert msgs[0]["content"] == "[Document: https://example.com/report.pdf]"

    def test_document_with_image_media_type(self):
        """Document block with image/ media type should be passed as an image."""
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "image/tiff",
                            "data": "TIFFDATA",
                        },
                    },
                ],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        content = msgs[0]["content"]
        assert content[0]["type"] == "image_url"
        assert content[0]["image_url"]["url"] == "data:image/tiff;base64,TIFFDATA"

    def test_document_default_media_type(self):
        """Document without media_type defaults to application/pdf."""
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {"type": "base64", "data": "somedata"},
                    },
                ],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        # Single text part collapses to string content
        assert msgs[0]["content"] == "[Document: application/pdf]"

    def test_text_image_document_mixed(self):
        """All three content types mixed in one message."""
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyze these:"},
                    {
                        "type": "image",
                        "source": {"type": "url", "url": "https://example.com/chart.png"},
                    },
                    {
                        "type": "document",
                        "source": {"type": "base64", "media_type": "application/pdf", "data": "PDF"},
                    },
                ],
            }],
        }
        msgs = anthropic_compat._convert_messages(body)
        content = msgs[0]["content"]
        assert len(content) == 3
        assert content[0] == {"type": "text", "text": "Analyze these:"}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == "https://example.com/chart.png"
        assert content[2] == {"type": "text", "text": "[Document: application/pdf]"}


# ---------------------------------------------------------------------------
# anthropic-version response header
# ---------------------------------------------------------------------------

class TestAnthropicVersionHeader:
    """Verify anthropic-version header is present in all response paths."""

    def setup_method(self):
        import config as _cfg
        _cfg.BOOST_AUTH = []

    def test_non_streaming_response_has_anthropic_version(self):
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
        assert resp.headers.get("anthropic-version") == "2023-06-01"

    def test_streaming_response_has_anthropic_version(self):
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
        assert resp.headers.get("anthropic-version") == "2023-06-01"

    def test_direct_task_response_has_anthropic_version(self):
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
        assert resp.headers.get("anthropic-version") == "2023-06-01"

    def test_count_tokens_response_has_anthropic_version(self):
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
        assert resp.headers.get("anthropic-version") == "2023-06-01"

    def test_error_response_has_anthropic_version(self):
        client = TestClient(_integration_app, raise_server_exceptions=False)
        resp = client.post("/v1/messages", json={
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
        })
        # Missing model -> 400
        assert resp.status_code == 400
        assert resp.headers.get("anthropic-version") == "2023-06-01"

    def test_anthropic_headers_helper_without_request_id(self):
        headers = anthropic_compat._anthropic_headers()
        assert headers["anthropic-version"] == "2023-06-01"
        assert "request-id" not in headers

    def test_anthropic_headers_helper_with_request_id(self):
        headers = anthropic_compat._anthropic_headers("req_abc123")
        assert headers["anthropic-version"] == "2023-06-01"
        assert headers["request-id"] == "req_abc123"


# ---------------------------------------------------------------------------
# Improved stop_sequences handling
# ---------------------------------------------------------------------------

class TestStopSequenceHandling:
    """Test stop_sequence detection in non-streaming and streaming paths."""

    def test_stop_reason_with_matching_sequence_among_multiple(self):
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=["\n\nHuman:", "\n\nAssistant:", "STOP"],
            content_text="Here is some textSTOP",
        )
        assert reason == "stop_sequence"
        assert seq == "STOP"

    def test_stop_reason_matches_first_applicable_sequence(self):
        # When multiple sequences could match, the first in the list wins
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=["end", "the end"],
            content_text="This is the end",
        )
        assert reason == "stop_sequence"
        assert seq == "end"

    def test_stop_reason_with_empty_content(self):
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=["\n\nHuman:"],
            content_text="",
        )
        # Empty string can't match — defaults to first stop sequence
        assert reason == "stop_sequence"
        assert seq == "\n\nHuman:"

    def test_stop_reason_content_with_trailing_whitespace(self):
        # rstrip() is applied before checking
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=["\n\nHuman:"],
            content_text="Hello\n\nHuman:   ",
        )
        assert reason == "stop_sequence"
        assert seq == "\n\nHuman:"

    def test_stop_reason_no_sequences_is_end_turn(self):
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=None,
            content_text="Hello world",
        )
        assert reason == "end_turn"
        assert seq is None

    def test_stop_reason_empty_sequences_list_is_end_turn(self):
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=[],
            content_text="Hello world",
        )
        assert reason == "end_turn"
        assert seq is None

    def test_non_streaming_stop_sequence_in_response(self):
        """Non-streaming response includes stop_sequence field when sequence matched."""
        import config as _cfg
        _cfg.BOOST_AUTH = []

        openai_result = _fake_openai_result(
            content="Hello\n\nHuman:",
            finish_reason="stop",
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
            resp = client.post("/v1/messages", json={
                **_ANTHRO_BODY,
                "stop_sequences": ["\n\nHuman:"],
            })

        assert resp.status_code == 200
        body = resp.json()
        assert body["stop_reason"] == "stop_sequence"
        assert body["stop_sequence"] == "\n\nHuman:"

    def test_non_streaming_no_match_defaults_to_first_sequence(self):
        """Non-streaming response with stop_sequences but no match defaults to first sequence."""
        import config as _cfg
        _cfg.BOOST_AUTH = []

        openai_result = _fake_openai_result(
            content="Hello world",
            finish_reason="stop",
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
            resp = client.post("/v1/messages", json={
                **_ANTHRO_BODY,
                "stop_sequences": ["\n\nHuman:"],
            })

        assert resp.status_code == 200
        body = resp.json()
        assert body["stop_reason"] == "stop_sequence"
        assert body["stop_sequence"] == "\n\nHuman:"

    @pytest.mark.asyncio
    async def test_streaming_stop_sequence_in_message_delta(self):
        """Streaming message_delta includes stop_sequence when sequence matched."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hello\\n\\nHuman:"}}]}\n\n'
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
                '"usage": {"prompt_tokens": 5, "completion_tokens": 2}}\n\n'
            )

        events = []
        async for event in anthropic_compat._anthropic_stream_converter(
            response_stream(), "claude-test",
            stop_sequences=["\n\nHuman:"],
        ):
            events.append(event)

        # Find message_delta
        for event in events:
            if '"type": "message_delta"' in event:
                data_line = [l for l in event.strip().split("\n") if l.startswith("data: ")][0]
                payload = json.loads(data_line[6:])
                assert payload["delta"]["stop_reason"] == "stop_sequence"
                assert payload["delta"]["stop_sequence"] == "\n\nHuman:"
                break
        else:
            pytest.fail("No message_delta event found")

    @pytest.mark.asyncio
    async def test_streaming_no_match_defaults_to_first_sequence(self):
        """Streaming message_delta defaults to first stop_sequence when none match."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hello world"}}]}\n\n'
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
                '"usage": {"prompt_tokens": 5, "completion_tokens": 2}}\n\n'
            )

        events = []
        async for event in anthropic_compat._anthropic_stream_converter(
            response_stream(), "claude-test",
            stop_sequences=["\n\nHuman:"],
        ):
            events.append(event)

        for event in events:
            if '"type": "message_delta"' in event:
                data_line = [l for l in event.strip().split("\n") if l.startswith("data: ")][0]
                payload = json.loads(data_line[6:])
                assert payload["delta"]["stop_reason"] == "stop_sequence"
                assert payload["delta"]["stop_sequence"] == "\n\nHuman:"
                break
        else:
            pytest.fail("No message_delta event found")

    @pytest.mark.asyncio
    async def test_streaming_stop_sequence_with_multiple_sequences(self):
        """Streaming correctly identifies which stop sequence matched."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Result\\n\\nAssistant:"}}]}\n\n'
            yield (
                'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
                '"usage": {"prompt_tokens": 5, "completion_tokens": 3}}\n\n'
            )

        events = []
        async for event in anthropic_compat._anthropic_stream_converter(
            response_stream(), "claude-test",
            stop_sequences=["\n\nHuman:", "\n\nAssistant:"],
        ):
            events.append(event)

        for event in events:
            if '"type": "message_delta"' in event:
                data_line = [l for l in event.strip().split("\n") if l.startswith("data: ")][0]
                payload = json.loads(data_line[6:])
                assert payload["delta"]["stop_reason"] == "stop_sequence"
                assert payload["delta"]["stop_sequence"] == "\n\nAssistant:"
                break
        else:
            pytest.fail("No message_delta event found")


# ===========================================================================
# Message Batches stubs
# ===========================================================================

class TestMessageBatchesStubs:
    """All batch endpoints return proper Anthropic-format errors."""

    def test_create_batch_returns_501(self):
        client = _make_client()
        resp = client.post("/v1/messages/batches", json={"requests": []})
        assert resp.status_code == 501
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "not_supported_error"
        assert "not supported" in body["error"]["message"]

    def test_list_batches_returns_501(self):
        client = _make_client()
        resp = client.get("/v1/messages/batches")
        assert resp.status_code == 501
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "not_supported_error"

    def test_get_batch_returns_404(self):
        client = _make_client()
        resp = client.get("/v1/messages/batches/batch_abc123")
        assert resp.status_code == 404
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "not_found_error"
        assert "batch_abc123" in body["error"]["message"]

    def test_get_batch_results_returns_404(self):
        client = _make_client()
        resp = client.get("/v1/messages/batches/batch_abc123/results")
        assert resp.status_code == 404
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "not_found_error"
        assert "batch_abc123" in body["error"]["message"]

    def test_cancel_batch_returns_404(self):
        client = _make_client()
        resp = client.post("/v1/messages/batches/batch_abc123/cancel")
        assert resp.status_code == 404
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "not_found_error"
        assert "batch_abc123" in body["error"]["message"]

    def test_batch_endpoints_include_request_id_header(self):
        client = _make_client()
        for method, path in [
            ("post", "/v1/messages/batches"),
            ("get", "/v1/messages/batches"),
            ("get", "/v1/messages/batches/batch_x"),
            ("get", "/v1/messages/batches/batch_x/results"),
            ("post", "/v1/messages/batches/batch_x/cancel"),
        ]:
            resp = getattr(client, method)(path)
            assert "request-id" in resp.headers, f"Missing request-id on {method.upper()} {path}"
            assert resp.headers["request-id"].startswith("req_")

    def test_batch_endpoints_include_anthropic_version_header(self):
        client = _make_client()
        for method, path in [
            ("post", "/v1/messages/batches"),
            ("get", "/v1/messages/batches"),
            ("get", "/v1/messages/batches/batch_x"),
        ]:
            resp = getattr(client, method)(path)
            assert resp.headers.get("anthropic-version") == "2023-06-01"

    def test_batch_endpoints_require_auth(self):
        client = _make_client(auth_key="secret-key")
        resp = client.post("/v1/messages/batches", json={})
        assert resp.status_code == 401

        resp = client.get("/v1/messages/batches")
        assert resp.status_code == 401

    def test_batch_create_with_auth(self):
        client = _make_client(auth_key="secret-key")
        resp = client.post(
            "/v1/messages/batches",
            json={},
            headers={"Authorization": "Bearer secret-key"},
        )
        assert resp.status_code == 501


# ---------------------------------------------------------------------------
# Streaming ping event
# ---------------------------------------------------------------------------

class TestStreamingPingEvent:
    """Verify that a ping event is emitted immediately after message_start."""

    @pytest.mark.asyncio
    async def test_ping_emitted_after_message_start(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "claude-test")
        ]

        # First event is message_start, second should be ping
        assert len(events) >= 2
        assert "message_start" in events[0]
        assert "event: ping" in events[1]
        assert '"data": {}' not in events[1]  # data should be {} (the object)
        assert "data: {}" in events[1]

    @pytest.mark.asyncio
    async def test_ping_is_valid_sse(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "x"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]

        ping_event = events[1]
        # Should be a well-formed SSE event with event type and data
        assert ping_event.startswith("event: ping\n")
        assert ping_event.endswith("\n\n")

    @pytest.mark.asyncio
    async def test_ping_before_content_blocks(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]

        # Verify ordering: message_start, ping, content_block_start, ...
        event_types = []
        for e in events:
            if "event: " in e:
                event_type = e.split("event: ")[1].split("\n")[0]
                event_types.append(event_type)

        assert event_types[0] == "message_start"
        assert event_types[1] == "ping"
        assert event_types[2] == "content_block_start"

    @pytest.mark.asyncio
    async def test_ping_present_in_empty_stream(self):
        """Even when the backend sends no content, ping should still be emitted."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]

        joined = "".join(events)
        assert "event: ping" in joined

    @pytest.mark.asyncio
    async def test_only_one_ping_emitted(self):
        """Exactly one ping event should be emitted per stream."""
        async def response_stream():
            for i in range(10):
                yield f'data: {{"choices": [{{"delta": {{"content": "chunk{i}"}}}}]}}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]

        ping_count = sum(1 for e in events if "event: ping" in e)
        assert ping_count == 1


# ---------------------------------------------------------------------------
# Comprehensive error type mapping
# ---------------------------------------------------------------------------

class TestErrorTypeMapping:
    """Verify all Anthropic error types map correctly per the spec."""

    def test_400_invalid_request_error(self):
        resp = anthropic_compat._anthropic_error(400, "bad request")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "invalid_request_error"

    def test_401_authentication_error(self):
        resp = anthropic_compat._anthropic_error(401, "unauthorized")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "authentication_error"

    def test_403_permission_error(self):
        resp = anthropic_compat._anthropic_error(403, "forbidden")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "permission_error"

    def test_404_not_found_error(self):
        resp = anthropic_compat._anthropic_error(404, "not found")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "not_found_error"

    def test_429_rate_limit_error(self):
        resp = anthropic_compat._anthropic_error(429, "rate limited")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "rate_limit_error"

    def test_500_api_error(self):
        resp = anthropic_compat._anthropic_error(500, "internal error")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "api_error"

    def test_529_overloaded_error(self):
        resp = anthropic_compat._anthropic_error(529, "overloaded")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "overloaded_error"

    def test_unknown_status_defaults_to_api_error(self):
        resp = anthropic_compat._anthropic_error(502, "bad gateway")
        body = json.loads(resp.body.decode())
        assert body["error"]["type"] == "api_error"

    def test_error_map_has_all_anthropic_spec_codes(self):
        expected_codes = {400, 401, 403, 404, 429, 500, 529}
        assert set(anthropic_compat.ERROR_TYPE_MAP.keys()) == expected_codes

    def test_error_response_format(self):
        for code, expected_type in anthropic_compat.ERROR_TYPE_MAP.items():
            resp = anthropic_compat._anthropic_error(code, f"error {code}")
            assert resp.status_code == code
            body = json.loads(resp.body.decode())
            assert body["type"] == "error"
            assert body["error"]["type"] == expected_type
            assert body["error"]["message"] == f"error {code}"

    def test_error_with_request_id(self):
        resp = anthropic_compat._anthropic_error(400, "bad", request_id="req_123")
        assert resp.headers.get("request-id") == "req_123"


# ---------------------------------------------------------------------------
# tool_result content handling edge cases
# ---------------------------------------------------------------------------

class TestToolResultContentHandling:
    """Verify tool_result content blocks handle string, array, images, and is_error."""

    def test_tool_result_string_content(self):
        """Simple string content is passed through directly."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "content": "simple result",
            },
        ])
        assert len(msgs) == 1
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["content"] == "simple result"

    def test_tool_result_empty_string_content(self):
        """Empty string content is allowed."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "content": "",
            },
        ])
        assert msgs[0]["content"] == ""

    def test_tool_result_no_content_field(self):
        """Missing content field defaults to empty string."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
            },
        ])
        assert msgs[0]["content"] == ""

    def test_tool_result_array_of_text_blocks(self):
        """Array with multiple text blocks is joined with newlines."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "content": [
                    {"type": "text", "text": "line 1"},
                    {"type": "text", "text": "line 2"},
                ],
            },
        ])
        assert msgs[0]["content"] == "line 1\nline 2"

    def test_tool_result_array_single_text_block(self):
        """Array with one text block extracts the text."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "content": [
                    {"type": "text", "text": "only line"},
                ],
            },
        ])
        assert msgs[0]["content"] == "only line"

    def test_tool_result_array_with_base64_image(self):
        """Image blocks in tool_result content produce a follow-up user message."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "content": [
                    {"type": "text", "text": "Screenshot captured"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "iVBORw0KGgo=",
                        },
                    },
                ],
            },
        ])
        # First message: tool result with text
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["content"] == "Screenshot captured"
        # Second message: user message with the image
        assert len(msgs) == 2
        assert msgs[1]["role"] == "user"
        assert isinstance(msgs[1]["content"], list)
        assert msgs[1]["content"][0]["type"] == "image_url"
        assert msgs[1]["content"][0]["image_url"]["url"] == "data:image/png;base64,iVBORw0KGgo="

    def test_tool_result_array_with_url_image(self):
        """URL-based images in tool_result content are also extracted."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "content": [
                    {"type": "text", "text": "Here is the chart"},
                    {
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": "https://example.com/chart.png",
                        },
                    },
                ],
            },
        ])
        assert msgs[0]["content"] == "Here is the chart"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"][0]["image_url"]["url"] == "https://example.com/chart.png"

    def test_tool_result_array_with_multiple_images(self):
        """Multiple images in tool_result produce one user message with all images."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "content": [
                    {"type": "text", "text": "Screenshots"},
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": "AAA"},
                    },
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": "BBB"},
                    },
                ],
            },
        ])
        assert len(msgs) == 2
        assert msgs[1]["role"] == "user"
        assert len(msgs[1]["content"]) == 2
        assert msgs[1]["content"][0]["image_url"]["url"] == "data:image/png;base64,AAA"
        assert msgs[1]["content"][1]["image_url"]["url"] == "data:image/jpeg;base64,BBB"

    def test_tool_result_array_image_only_no_text(self):
        """Image-only tool_result (no text) still works."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": "IMGDATA"},
                    },
                ],
            },
        ])
        # Tool message has empty content (no text blocks)
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["content"] == ""
        # Image is in follow-up user message
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"][0]["image_url"]["url"] == "data:image/png;base64,IMGDATA"

    def test_tool_result_array_image_default_media_type(self):
        """Image block without media_type defaults to image/png."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "content": [
                    {
                        "type": "image",
                        "source": {"data": "XYZ"},
                    },
                ],
            },
        ])
        assert msgs[1]["content"][0]["image_url"]["url"] == "data:image/png;base64,XYZ"

    def test_tool_result_array_skips_non_dict_items(self):
        """Non-dict items in tool_result content array are silently skipped."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "content": [
                    "just a string, not a dict",
                    {"type": "text", "text": "valid text"},
                ],
            },
        ])
        assert msgs[0]["content"] == "valid text"


class TestToolResultIsError:
    """Verify is_error flag handling on tool_result blocks."""

    def test_is_error_true_with_content(self):
        """is_error: true prefixes content with 'Error: '."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "is_error": True,
                "content": "file not found",
            },
        ])
        assert msgs[0]["content"] == "Error: file not found"

    def test_is_error_true_with_array_content(self):
        """is_error: true works with array content too."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "is_error": True,
                "content": [
                    {"type": "text", "text": "connection refused"},
                ],
            },
        ])
        assert msgs[0]["content"] == "Error: connection refused"

    def test_is_error_true_with_empty_content(self):
        """is_error: true with empty/missing content uses generic error message."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "is_error": True,
                "content": "",
            },
        ])
        assert msgs[0]["content"] == "Error: tool execution failed"

    def test_is_error_true_no_content_field(self):
        """is_error: true with no content field uses generic error message."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "is_error": True,
            },
        ])
        assert msgs[0]["content"] == "Error: tool execution failed"

    def test_is_error_false_does_not_prefix(self):
        """is_error: false (or absent) does not prefix content."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "is_error": False,
                "content": "some result",
            },
        ])
        assert msgs[0]["content"] == "some result"

    def test_is_error_absent_does_not_prefix(self):
        """is_error absent does not prefix content."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "content": "success result",
            },
        ])
        assert msgs[0]["content"] == "success result"

    def test_is_error_true_with_image_content(self):
        """is_error: true with image content still extracts images and prefixes text."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "is_error": True,
                "content": [
                    {"type": "text", "text": "screenshot of error page"},
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": "ERR"},
                    },
                ],
            },
        ])
        assert msgs[0]["content"] == "Error: screenshot of error page"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"][0]["image_url"]["url"] == "data:image/png;base64,ERR"

    def test_is_error_true_with_multiline_content(self):
        """is_error: true with multiline text content."""
        msgs = anthropic_compat._convert_user_message([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "is_error": True,
                "content": [
                    {"type": "text", "text": "Error code: 404"},
                    {"type": "text", "text": "Page not found"},
                ],
            },
        ])
        assert msgs[0]["content"] == "Error: Error code: 404\nPage not found"


class TestToolResultInConvertMessages:
    """Integration tests for tool_result through the full _convert_messages path."""

    def test_tool_result_with_image_in_full_conversation(self):
        """tool_result with image in a multi-turn conversation."""
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Let me take a screenshot."},
                        {
                            "type": "tool_use",
                            "id": "toolu_123",
                            "name": "screenshot",
                            "input": {},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_123",
                            "content": [
                                {"type": "text", "text": "Screenshot taken"},
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": "SCREENSHOT_DATA",
                                    },
                                },
                            ],
                        },
                    ],
                },
            ],
        }
        msgs = anthropic_compat._convert_messages(body)
        # assistant message
        assert msgs[0]["role"] == "assistant"
        # tool result
        assert msgs[1]["role"] == "tool"
        assert msgs[1]["content"] == "Screenshot taken"
        # follow-up user message with image
        assert msgs[2]["role"] == "user"
        assert msgs[2]["content"][0]["type"] == "image_url"

    def test_tool_result_is_error_in_full_conversation(self):
        """is_error tool_result in a multi-turn conversation."""
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_456",
                            "name": "read_file",
                            "input": {"path": "/nonexistent"},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_456",
                            "is_error": True,
                            "content": "No such file or directory",
                        },
                    ],
                },
            ],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert msgs[0]["role"] == "assistant"
        assert msgs[1]["role"] == "tool"
        assert msgs[1]["content"] == "Error: No such file or directory"

    def test_mixed_tool_results_and_text(self):
        """Tool results mixed with text in the same user message."""
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "result 1",
                        },
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_2",
                            "is_error": True,
                            "content": "failed",
                        },
                        {"type": "text", "text": "Please analyze these results"},
                    ],
                },
            ],
        }
        msgs = anthropic_compat._convert_messages(body)
        # tool_results come first
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["content"] == "result 1"
        assert msgs[1]["role"] == "tool"
        assert msgs[1]["content"] == "Error: failed"
        # then the user text
        assert msgs[2]["role"] == "user"
        assert msgs[2]["content"] == "Please analyze these results"


# ---------------------------------------------------------------------------
# Usage tracking in streaming
# ---------------------------------------------------------------------------


class TestStreamingUsageTracking:
    """Verify usage (input_tokens / output_tokens) is captured correctly
    from OpenAI-format streaming chunks and emitted in the Anthropic
    message_start and message_delta events."""

    @pytest.mark.asyncio
    async def test_message_start_has_zero_usage(self):
        """message_start is emitted before any chunks arrive, so usage must
        be zeros (we cannot know the prompt token count yet)."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":99,"completion_tokens":10}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(mock_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))
        msg_start = [e for e in parsed if e["type"] == "message_start"][0]
        assert msg_start["message"]["usage"]["input_tokens"] == 0
        assert msg_start["message"]["usage"]["output_tokens"] == 0

    @pytest.mark.asyncio
    async def test_message_delta_has_final_usage(self):
        """message_delta carries the accumulated usage from the stream."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":20,"completion_tokens":8}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(mock_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))
        msg_delta = [e for e in parsed if e["type"] == "message_delta"][0]
        assert msg_delta["usage"]["input_tokens"] == 20
        assert msg_delta["usage"]["output_tokens"] == 8

    @pytest.mark.asyncio
    async def test_usage_from_separate_final_chunk(self):
        """OpenAI backends with stream_options.include_usage send usage in a
        separate chunk with choices:[]. The converter must capture it."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            # Separate usage-only chunk (OpenAI pattern)
            yield 'data: {"choices":[],"usage":{"prompt_tokens":15,"completion_tokens":4}}\n\n'
            yield 'data: [DONE]\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(mock_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))
        msg_delta = [e for e in parsed if e["type"] == "message_delta"][0]
        assert msg_delta["usage"]["input_tokens"] == 15
        assert msg_delta["usage"]["output_tokens"] == 4

    @pytest.mark.asyncio
    async def test_no_usage_from_backend_defaults_to_zero(self):
        """When the backend sends no usage at all, both counts default to 0."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"yo"}}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(mock_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))
        msg_delta = [e for e in parsed if e["type"] == "message_delta"][0]
        assert msg_delta["usage"]["input_tokens"] == 0
        assert msg_delta["usage"]["output_tokens"] == 0

    @pytest.mark.asyncio
    async def test_usage_in_early_chunk_preserved(self):
        """If usage appears in an early chunk (not the final one), it should
        still be captured — later chunks without usage should not reset it."""
        async def mock_stream():
            # First chunk has usage
            yield 'data: {"choices":[{"delta":{"content":"a"}}],"usage":{"prompt_tokens":50,"completion_tokens":1}}\n\n'
            # Subsequent chunks have no usage
            yield 'data: {"choices":[{"delta":{"content":"b"}}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(mock_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))
        msg_delta = [e for e in parsed if e["type"] == "message_delta"][0]
        assert msg_delta["usage"]["input_tokens"] == 50
        # output_tokens stays at 1 from the first chunk
        assert msg_delta["usage"]["output_tokens"] == 1

    @pytest.mark.asyncio
    async def test_usage_updated_by_later_chunk(self):
        """When a later chunk carries updated usage (higher values), the
        converter should use the later values."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"a"}}],"usage":{"prompt_tokens":10,"completion_tokens":1}}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"b"}}],"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":9}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(mock_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))
        msg_delta = [e for e in parsed if e["type"] == "message_delta"][0]
        assert msg_delta["usage"]["input_tokens"] == 10
        # Should be the final non-zero value
        assert msg_delta["usage"]["output_tokens"] == 9

    @pytest.mark.asyncio
    async def test_message_delta_has_cache_usage_fields(self):
        """message_delta.usage must include cache usage fields (always 0)."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(mock_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))
        msg_delta = [e for e in parsed if e["type"] == "message_delta"][0]
        assert msg_delta["usage"]["cache_creation_input_tokens"] == 0
        assert msg_delta["usage"]["cache_read_input_tokens"] == 0

    @pytest.mark.asyncio
    async def test_message_start_has_cache_usage_fields(self):
        """message_start.usage must include cache usage fields (always 0)."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(mock_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))
        msg_start = [e for e in parsed if e["type"] == "message_start"][0]
        assert msg_start["message"]["usage"]["cache_creation_input_tokens"] == 0
        assert msg_start["message"]["usage"]["cache_read_input_tokens"] == 0

    @pytest.mark.asyncio
    async def test_stream_with_tool_calls_captures_usage(self):
        """Usage is captured correctly even when the stream contains tool calls."""
        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"foo","arguments":"{"}}]}}]}\n\n'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"}"}}]}}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":30,"completion_tokens":12}}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(mock_stream(), "m")
        ]
        parsed = _parse_sse_events("".join(events))
        msg_delta = [e for e in parsed if e["type"] == "message_delta"][0]
        assert msg_delta["usage"]["input_tokens"] == 30
        assert msg_delta["usage"]["output_tokens"] == 12


# ---------------------------------------------------------------------------
# Usage tracking in Responses API streaming
# ---------------------------------------------------------------------------


class TestResponsesStreamingUsageTracking:
    """Verify usage tracking in the Responses API streaming converter."""

    @pytest.mark.asyncio
    async def test_no_usage_from_backend(self):
        """When backend sends no usage at all, completed event has zeros."""
        import responses_compat

        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_nu"
        ):
            events.append(event)

        parsed = _parse_sse_events_responses(events)
        completed = [d for t, d in parsed if t == "response.completed"]
        usage = completed[0]["response"]["usage"]
        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0
        assert usage["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_usage_in_early_chunk_preserved(self):
        """Usage from an early chunk is preserved when later chunks lack it."""
        import responses_compat

        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"x"}}],"usage":{"prompt_tokens":25,"completion_tokens":3}}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"y"}}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_early"
        ):
            events.append(event)

        parsed = _parse_sse_events_responses(events)
        completed = [d for t, d in parsed if t == "response.completed"]
        usage = completed[0]["response"]["usage"]
        assert usage["input_tokens"] == 25
        assert usage["output_tokens"] == 3

    @pytest.mark.asyncio
    async def test_usage_with_tool_calls(self):
        """Usage is captured when stream contains tool calls."""
        import responses_compat

        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"fn","arguments":"{}"}}]}}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":40,"completion_tokens":15}}\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_tc"
        ):
            events.append(event)

        parsed = _parse_sse_events_responses(events)
        completed = [d for t, d in parsed if t == "response.completed"]
        usage = completed[0]["response"]["usage"]
        assert usage["input_tokens"] == 40
        assert usage["output_tokens"] == 15

    @pytest.mark.asyncio
    async def test_completed_usage_has_token_details(self):
        """The completed event usage must include input/output_tokens_details."""
        import responses_compat

        async def mock_stream():
            yield 'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n'

        events = []
        async for event in responses_compat._responses_stream_converter(
            mock_stream(), "model", "resp_det"
        ):
            events.append(event)

        parsed = _parse_sse_events_responses(events)
        completed = [d for t, d in parsed if t == "response.completed"]
        usage = completed[0]["response"]["usage"]
        assert "input_tokens_details" in usage
        assert usage["input_tokens_details"]["cached_tokens"] == 0
        assert "output_tokens_details" in usage
        assert usage["output_tokens_details"]["reasoning_tokens"] == 0


def _parse_sse_events_responses(raw_events):
    """Parse Responses API SSE strings into (event_type, data_dict) tuples."""
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


# ---------------------------------------------------------------------------
# Fix: _map_stop_reason defaults to stop_sequence when sequences configured
# ---------------------------------------------------------------------------

class TestMapStopReasonDefaultToStopSequence:
    """When stop_sequences are configured and finish_reason is 'stop', the
    fallback should be stop_sequence (first configured) because OpenAI
    backends strip stop sequences from output text."""

    def test_non_matching_content_defaults_to_first_sequence(self):
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=["<END>", "STOP"],
            content_text="Hello world",
        )
        assert reason == "stop_sequence"
        assert seq == "<END>"

    def test_no_content_defaults_to_first_sequence(self):
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=["<END>"],
            content_text=None,
        )
        assert reason == "stop_sequence"
        assert seq == "<END>"

    def test_empty_content_defaults_to_first_sequence(self):
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=["STOP"],
            content_text="",
        )
        assert reason == "stop_sequence"
        assert seq == "STOP"

    def test_matching_content_still_returns_matched_sequence(self):
        """When the text does end with a stop sequence, that one is returned."""
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=["<END>", "STOP"],
            content_text="Hello worldSTOP",
        )
        assert reason == "stop_sequence"
        assert seq == "STOP"

    def test_length_finish_reason_ignores_stop_sequences(self):
        """finish_reason 'length' always maps to max_tokens regardless."""
        reason, seq = anthropic_compat._map_stop_reason(
            "length",
            stop_sequences=["<END>"],
            content_text="Hello world",
        )
        assert reason == "max_tokens"
        assert seq is None

    def test_tool_calls_finish_reason_ignores_stop_sequences(self):
        """finish_reason 'tool_calls' always maps to tool_use."""
        reason, seq = anthropic_compat._map_stop_reason(
            "tool_calls",
            stop_sequences=["<END>"],
            content_text="Hello world",
        )
        assert reason == "tool_use"
        assert seq is None

    def test_no_sequences_configured_returns_end_turn(self):
        """Without stop_sequences, 'stop' still maps to end_turn."""
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=None,
            content_text="Hello world",
        )
        assert reason == "end_turn"
        assert seq is None

    def test_empty_sequences_list_returns_end_turn(self):
        """Empty stop_sequences list still maps to end_turn."""
        reason, seq = anthropic_compat._map_stop_reason(
            "stop",
            stop_sequences=[],
            content_text="Hello world",
        )
        assert reason == "end_turn"
        assert seq is None


# ---------------------------------------------------------------------------
# Fix: clean_text_preserve_newlines percent decoding
# ---------------------------------------------------------------------------

class TestCleanTextPercentDecoding:
    """clean_text_preserve_newlines should URL-decode percent-encoded text."""

    def test_decodes_percent_encoded_colon(self):
        import format
        result = format.clean_text_preserve_newlines("hello%3Aworld")
        assert result == "hello:world"

    def test_decodes_percent_encoded_space(self):
        import format
        result = format.clean_text_preserve_newlines("hello%20world")
        assert result == "hello world"

    def test_decodes_multiple_percent_sequences(self):
        import format
        result = format.clean_text_preserve_newlines("key%3Dvalue%26other%3D2")
        assert result == "key=value&other=2"

    def test_preserves_already_decoded_text(self):
        import format
        result = format.clean_text_preserve_newlines("hello world")
        assert result == "hello world"

    def test_preserves_newlines_after_decoding(self):
        import format
        result = format.clean_text_preserve_newlines("line1%3A%20foo\nline2%3A%20bar")
        assert result == "line1: foo\nline2: bar"

    def test_decodes_percent_encoded_slash(self):
        import format
        result = format.clean_text_preserve_newlines("path%2Fto%2Ffile")
        assert result == "path/to/file"

    def test_handles_mixed_encoded_and_plain(self):
        import format
        result = format.clean_text_preserve_newlines("Hello%2C world%21 How are you%3F")
        assert result == "Hello, world! How are you?"


if __name__ == "__main__":
    unittest.main()
