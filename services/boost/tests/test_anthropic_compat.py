"""Tests for Boost's Anthropic-compatible Messages API translation layer."""

import json
import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

import pytest

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, SRC_DIR)
os.chdir(SRC_DIR)

# Mock heavy modules that anthropic_compat imports but tests don't exercise.
# mapper requires asyncache/litellm which may not be installed in test envs.
for mod_name in ("mapper", "llm"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

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
        extra = anthropic_compat._synthesize_authorization(request)

        assert extra["authorization"] == "Bearer sk-anthropic"
        assert request.headers["authorization"] == "Bearer sk-anthropic"

    def test_preserves_explicit_authorization_header(self):
        request = make_request({
            "authorization": "Bearer explicit-token",
            "x-api-key": "sk-anthropic",
        })
        extra = anthropic_compat._synthesize_authorization(request)

        assert extra["authorization"] == "Bearer explicit-token"
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


# ---------------------------------------------------------------------------
# _has_complete_tool_call_arguments
# ---------------------------------------------------------------------------

class TestHasCompleteToolCallArguments:
    def test_valid_json_object(self):
        assert anthropic_compat._has_complete_tool_call_arguments('{"key": "value"}') is True

    def test_empty_object(self):
        assert anthropic_compat._has_complete_tool_call_arguments("{}") is True

    def test_incomplete_json(self):
        assert anthropic_compat._has_complete_tool_call_arguments('{"key": "val') is False

    def test_json_array(self):
        assert anthropic_compat._has_complete_tool_call_arguments('[1, 2, 3]') is False

    def test_not_string(self):
        assert anthropic_compat._has_complete_tool_call_arguments(42) is False

    def test_empty_string(self):
        assert anthropic_compat._has_complete_tool_call_arguments("") is False

    def test_none(self):
        assert anthropic_compat._has_complete_tool_call_arguments(None) is False


if __name__ == "__main__":
    unittest.main()
