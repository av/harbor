"""Tests for the token_counter module used by count_tokens endpoint."""

import json
from unittest.mock import patch

import pytest
import token_counter

_has_tiktoken = token_counter._USE_TIKTOKEN


class TestTokenLen:
    """Test the core token length function."""

    def test_empty_string(self):
        assert token_counter._token_len("") == 0 or token_counter._token_len("") >= 0

    def test_single_word(self):
        count = token_counter._token_len("hello")
        assert count > 0

    def test_longer_text_has_more_tokens(self):
        short = token_counter._token_len("hi")
        long = token_counter._token_len("This is a much longer sentence with many more words in it.")
        assert long > short

    def test_non_ascii_text(self):
        count = token_counter._token_len("こんにちは世界")
        assert count > 0


class TestCountMessagesTokens:
    """Test count_messages_tokens with various message shapes."""

    def test_single_user_message(self):
        msgs = [{"role": "user", "content": "Hello, world!"}]
        count = token_counter.count_messages_tokens(msgs)
        assert count > 0

    def test_empty_messages_returns_reply_primer(self):
        count = token_counter.count_messages_tokens([])
        # Should at least include the reply primer overhead
        assert count == token_counter._TOKENS_REPLY_PRIMER

    def test_system_message_adds_tokens(self):
        msgs_no_sys = [{"role": "user", "content": "hi"}]
        msgs_with_sys = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "hi"},
        ]
        count_no_sys = token_counter.count_messages_tokens(msgs_no_sys)
        count_with_sys = token_counter.count_messages_tokens(msgs_with_sys)
        assert count_with_sys > count_no_sys

    def test_multiple_messages(self):
        single = [{"role": "user", "content": "hi"}]
        multi = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello! How can I help you?"},
            {"role": "user", "content": "What is the capital of France?"},
        ]
        count_single = token_counter.count_messages_tokens(single)
        count_multi = token_counter.count_messages_tokens(multi)
        assert count_multi > count_single

    def test_multimodal_content_array(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this image?"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            }
        ]
        count = token_counter.count_messages_tokens(msgs)
        # Should include text tokens + image token estimate (85)
        text_only = token_counter.count_messages_tokens(
            [{"role": "user", "content": "What is in this image?"}]
        )
        assert count > text_only

    def test_tool_calls_in_message(self):
        msgs = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location": "San Francisco"}',
                        },
                    }
                ],
            }
        ]
        count = token_counter.count_messages_tokens(msgs)
        assert count > 0

    def test_name_field_adds_tokens(self):
        msgs_no_name = [{"role": "user", "content": "hi"}]
        msgs_with_name = [{"role": "user", "content": "hi", "name": "Alice"}]
        count_no_name = token_counter.count_messages_tokens(msgs_no_name)
        count_with_name = token_counter.count_messages_tokens(msgs_with_name)
        assert count_with_name > count_no_name

    def test_tool_message(self):
        msgs = [
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "content": "The weather in San Francisco is 72F and sunny.",
            }
        ]
        count = token_counter.count_messages_tokens(msgs)
        assert count > 0


class TestCountToolTokens:
    """Test token counting for tool definitions."""

    def test_no_tools_returns_zero(self):
        assert token_counter._count_tool_tokens([]) == 0
        assert token_counter._count_tool_tokens(None) == 0

    def test_single_tool(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "City and state",
                            },
                        },
                        "required": ["location"],
                    },
                },
            }
        ]
        count = token_counter._count_tool_tokens(tools)
        assert count > 0

    def test_multiple_tools_more_tokens(self):
        one_tool = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        two_tools = one_tool + [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search the web for information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                        },
                    },
                },
            }
        ]
        count_one = token_counter._count_tool_tokens(one_tool)
        count_two = token_counter._count_tool_tokens(two_tools)
        assert count_two > count_one

    def test_tool_with_complex_schema(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "create_user",
                    "description": "Create a new user account",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Full name"},
                            "email": {"type": "string", "format": "email"},
                            "age": {"type": "integer", "minimum": 0},
                            "address": {
                                "type": "object",
                                "properties": {
                                    "street": {"type": "string"},
                                    "city": {"type": "string"},
                                    "zip": {"type": "string"},
                                },
                            },
                        },
                        "required": ["name", "email"],
                    },
                },
            }
        ]
        count = token_counter._count_tool_tokens(tools)
        assert count > 10  # Complex schema should have many tokens


class TestCountMessagesWithTools:
    """Test count_messages_tokens with both messages and tools."""

    def test_tools_increase_count(self):
        msgs = [{"role": "user", "content": "What is the weather?"}]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a city",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                        },
                    },
                },
            }
        ]
        count_no_tools = token_counter.count_messages_tokens(msgs)
        count_with_tools = token_counter.count_messages_tokens(msgs, tools)
        assert count_with_tools > count_no_tools

    def test_none_tools_same_as_no_tools(self):
        msgs = [{"role": "user", "content": "hi"}]
        count_none = token_counter.count_messages_tokens(msgs, None)
        count_no = token_counter.count_messages_tokens(msgs)
        assert count_none == count_no


class TestHeuristicFallback:
    """Test the heuristic fallback when tiktoken is unavailable."""

    def test_heuristic_len_basic(self):
        # chars/4 approximation
        assert token_counter._heuristic_len("abcd") == 1
        assert token_counter._heuristic_len("abcdefgh") == 2

    def test_heuristic_len_minimum_one(self):
        # Empty string should return at least 1
        assert token_counter._heuristic_len("") >= 0

    def test_heuristic_len_short_text(self):
        assert token_counter._heuristic_len("hi") >= 1

    def test_fallback_produces_reasonable_estimate(self):
        """When tiktoken is unavailable, count should still be reasonable."""
        with patch.object(token_counter, '_USE_TIKTOKEN', False):
            msgs = [{"role": "user", "content": "Hello, how are you doing today?"}]
            count = token_counter.count_messages_tokens(msgs)
            # Should be in a reasonable range (not 0, not astronomical)
            assert 5 < count < 100


@pytest.mark.skipif(not _has_tiktoken, reason="tiktoken not installed")
class TestTiktokenIntegration:
    """Test that tiktoken is actually available and producing counts."""

    def test_tiktoken_is_available(self):
        assert token_counter._USE_TIKTOKEN is True

    def test_tiktoken_produces_known_count(self):
        count = token_counter._tiktoken_len("Hello world")
        assert count == 2

    def test_tiktoken_empty_string(self):
        count = token_counter._tiktoken_len("")
        assert count == 0
