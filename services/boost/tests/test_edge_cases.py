"""Edge case tests for compat layer boundary conditions.

Covers unusual inputs that are syntactically valid but semantically
unusual: zero/negative params, unicode model names, empty arguments,
special characters in tool names, large payloads, and type coercion.
"""

import json
import asyncio
import unittest

import pytest

import anthropic_compat
import responses_compat
from compat_utils import (
    to_anthropic_tool_id,
    to_openai_tool_id,
    sse_event,
    get_chunk_content,
    get_chunk_tool_calls,
    parse_sse_chunks,
)
from helpers import (
    FakeLLM,
    make_request,
    openai_result,
    streaming_chunks,
    sse_chunk,
    parse_anthropic_sse_events,
    parse_responses_sse_events,
    make_anthropic_app,
    make_responses_app,
    make_client,
    setup_mock_llm,
    ANTHROPIC_BODY,
    RESPONSES_BODY,
)


# ---------------------------------------------------------------------------
# Anthropic: max_tokens validation edge cases
# ---------------------------------------------------------------------------


class TestMaxTokensValidation:
    """max_tokens must be a positive integer per the Anthropic API spec."""

    def test_max_tokens_zero_rejected(self):
        resp = anthropic_compat._validate_request({
            "model": "m",
            "max_tokens": 0,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp is not None
        body = json.loads(resp.body)
        assert resp.status_code == 400
        assert "positive" in body["error"]["message"]

    def test_max_tokens_negative_rejected(self):
        resp = anthropic_compat._validate_request({
            "model": "m",
            "max_tokens": -100,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp is not None
        assert resp.status_code == 400

    def test_max_tokens_float_zero_rejected(self):
        resp = anthropic_compat._validate_request({
            "model": "m",
            "max_tokens": 0.0,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp is not None
        assert resp.status_code == 400

    def test_max_tokens_one_accepted(self):
        resp = anthropic_compat._validate_request({
            "model": "m",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp is None

    def test_max_tokens_large_accepted(self):
        resp = anthropic_compat._validate_request({
            "model": "m",
            "max_tokens": 200000,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp is None

    def test_max_tokens_string_rejected(self):
        resp = anthropic_compat._validate_request({
            "model": "m",
            "max_tokens": "128",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp is not None
        assert resp.status_code == 400

    def test_max_tokens_null_rejected(self):
        resp = anthropic_compat._validate_request({
            "model": "m",
            "max_tokens": None,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp is not None
        assert resp.status_code == 400

    def test_max_tokens_float_positive_accepted(self):
        """Float values like 128.0 should be accepted (they are numeric > 0)."""
        resp = anthropic_compat._validate_request({
            "model": "m",
            "max_tokens": 128.0,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp is None


class TestMaxTokensConvertParams:
    """_convert_params should handle max_tokens edge cases after validation."""

    def test_negative_max_tokens_not_forwarded(self):
        params = anthropic_compat._convert_params({"max_tokens": -10})
        assert "max_tokens" not in params

    def test_none_max_tokens_not_forwarded(self):
        params = anthropic_compat._convert_params({"max_tokens": None})
        assert "max_tokens" not in params

    def test_thinking_with_zero_max_tokens(self):
        """When thinking is enabled and max_tokens is 0, only budget_tokens count."""
        params = anthropic_compat._convert_params({
            "max_tokens": 0,
            "thinking": {"type": "enabled", "budget_tokens": 5000},
        })
        assert params["max_completion_tokens"] == 5000


# ---------------------------------------------------------------------------
# Unicode model names
# ---------------------------------------------------------------------------


class TestUnicodeModelNames:
    """Model names with non-ASCII characters should pass through unchanged."""

    def test_anthropic_unicode_model_passthrough(self):
        body = {
            "model": "claude-élève-3",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
        }
        openai_body = anthropic_compat._build_openai_body(body)
        assert openai_body["model"] == "claude-élève-3"

    def test_responses_unicode_model_passthrough(self):
        body = {"model": "模型-test", "input": "hello"}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["model"] == "模型-test"

    def test_anthropic_response_preserves_unicode_model(self):
        result = openai_result(content="Hi")
        resp = anthropic_compat._build_anthropic_response(
            result, "üñîçøðé"
        )
        assert resp["model"] == "üñîçøðé"

    def test_responses_response_preserves_unicode_model(self):
        result = openai_result(content="Hi")
        resp = responses_compat._build_responses_response(
            result, "üñîçøðé", "resp_123"
        )
        assert resp["model"] == "üñîçøðé"

    def test_emoji_model_name(self):
        body = {
            "model": "my-model-\U0001f680",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
        }
        err = anthropic_compat._validate_request(body)
        assert err is None
        openai_body = anthropic_compat._build_openai_body(body)
        assert openai_body["model"] == "my-model-\U0001f680"

    def test_cjk_model_name(self):
        body = {"model": "测试模型/v1", "input": "test"}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["model"] == "测试模型/v1"


# ---------------------------------------------------------------------------
# Very long model names
# ---------------------------------------------------------------------------


class TestLongModelNames:
    """No truncation should occur for long model names."""

    def test_anthropic_long_model_name(self):
        long_name = "a" * 10000
        body = {
            "model": long_name,
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
        }
        err = anthropic_compat._validate_request(body)
        assert err is None
        openai_body = anthropic_compat._build_openai_body(body)
        assert openai_body["model"] == long_name
        assert len(openai_body["model"]) == 10000

    def test_responses_long_model_name(self):
        long_name = "provider/org/" + "x" * 10000
        body = {"model": long_name, "input": "hi"}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["model"] == long_name

    def test_anthropic_response_long_model_not_truncated(self):
        long_name = "m" * 5000
        result = openai_result()
        resp = anthropic_compat._build_anthropic_response(result, long_name)
        assert resp["model"] == long_name


# ---------------------------------------------------------------------------
# Invalid base64 in image blocks
# ---------------------------------------------------------------------------


class TestInvalidBase64Images:
    """Invalid base64 data should be passed through to the backend as-is."""

    def test_anthropic_invalid_base64_passthrough(self):
        content = [{
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "NOT-VALID-BASE64!!!",
            },
        }]
        result = anthropic_compat._convert_user_message(content)
        assert len(result) == 1
        url = result[0]["content"][0]["image_url"]["url"]
        assert "NOT-VALID-BASE64!!!" in url

    def test_anthropic_empty_base64_data(self):
        content = [{
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": "",
            },
        }]
        result = anthropic_compat._convert_user_message(content)
        url = result[0]["content"][0]["image_url"]["url"]
        assert url == "data:image/jpeg;base64,"

    def test_responses_invalid_image_url_passthrough(self):
        parts = [{"type": "input_image", "image_url": "not-a-url"}]
        result = responses_compat._convert_content_parts(parts)
        assert isinstance(result, list)
        assert result[0]["image_url"]["url"] == "not-a-url"


# ---------------------------------------------------------------------------
# Deeply nested tool input_schema
# ---------------------------------------------------------------------------


class TestDeeplyNestedSchema:
    """Tool input_schema with deep nesting should pass through without issues."""

    def test_anthropic_deep_schema(self):
        # Build a 50-level deep schema
        schema = {"type": "string"}
        for _ in range(50):
            schema = {
                "type": "object",
                "properties": {"nested": schema},
            }
        body = {
            "tools": [{
                "name": "deep_tool",
                "description": "A deeply nested tool",
                "input_schema": schema,
            }],
        }
        tools = anthropic_compat._convert_tools(body)
        assert len(tools) == 1
        # Verify the schema is preserved at depth
        result = tools[0]["function"]["parameters"]
        for _ in range(50):
            assert result["type"] == "object"
            result = result["properties"]["nested"]
        assert result["type"] == "string"

    def test_responses_deep_schema(self):
        schema = {"type": "string"}
        for _ in range(50):
            schema = {
                "type": "object",
                "properties": {"nested": schema},
            }
        body = {
            "tools": [{
                "type": "function",
                "name": "deep_tool",
                "description": "nested",
                "parameters": schema,
            }],
        }
        tools = responses_compat._convert_tools(body)
        result = tools[0]["function"]["parameters"]
        for _ in range(50):
            result = result["properties"]["nested"]
        assert result["type"] == "string"


# ---------------------------------------------------------------------------
# Tool call with zero/empty arguments
# ---------------------------------------------------------------------------


class TestToolCallEmptyArguments:
    """Tool calls with empty or degenerate arguments should be handled safely."""

    def test_parse_empty_string_arguments(self):
        result = anthropic_compat._parse_tool_call_arguments("")
        assert result == {}

    def test_parse_null_arguments(self):
        result = anthropic_compat._parse_tool_call_arguments(None)
        assert result == {}

    def test_parse_non_dict_json(self):
        """Valid JSON that isn't an object should return empty dict."""
        assert anthropic_compat._parse_tool_call_arguments("42") == {}
        assert anthropic_compat._parse_tool_call_arguments("[1,2,3]") == {}
        assert anthropic_compat._parse_tool_call_arguments('"hello"') == {}
        assert anthropic_compat._parse_tool_call_arguments("true") == {}
        assert anthropic_compat._parse_tool_call_arguments("null") == {}

    def test_parse_valid_empty_dict(self):
        result = anthropic_compat._parse_tool_call_arguments("{}")
        assert result == {}

    def test_anthropic_response_tool_call_empty_args(self):
        """Tool call in response with empty arguments string."""
        result = openai_result(content=None, tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {"name": "my_tool", "arguments": ""},
        }], finish_reason="tool_calls")
        blocks = anthropic_compat._build_content_blocks(result)
        tool_blocks = [b for b in blocks if b["type"] == "tool_use"]
        assert len(tool_blocks) == 1
        assert tool_blocks[0]["input"] == {}

    def test_anthropic_response_tool_call_curly_brace_args(self):
        """Tool call with '{}' arguments produces empty input."""
        result = openai_result(content=None, tool_calls=[{
            "id": "call_2",
            "type": "function",
            "function": {"name": "no_args_tool", "arguments": "{}"},
        }], finish_reason="tool_calls")
        blocks = anthropic_compat._build_content_blocks(result)
        tool_blocks = [b for b in blocks if b["type"] == "tool_use"]
        assert tool_blocks[0]["input"] == {}

    def test_responses_tool_call_empty_args_in_output(self):
        """Responses API output item with empty arguments."""
        result = openai_result(content=None, tool_calls=[{
            "id": "call_3",
            "type": "function",
            "function": {"name": "ping", "arguments": ""},
        }], finish_reason="tool_calls")
        output = responses_compat._build_output_items(result)
        func_items = [o for o in output if o["type"] == "function_call"]
        assert len(func_items) == 1
        assert func_items[0]["arguments"] == ""


# ---------------------------------------------------------------------------
# High/extreme parameter values
# ---------------------------------------------------------------------------


class TestExtremeParameterValues:
    """Parameters at extreme values should pass through without modification."""

    def test_temperature_two(self):
        params = anthropic_compat._convert_params(
            {"max_tokens": 128, "temperature": 2.0}
        )
        assert params["temperature"] == 2.0

    def test_temperature_negative(self):
        """Negative temperature should pass through (backend validates)."""
        params = anthropic_compat._convert_params(
            {"max_tokens": 128, "temperature": -0.5}
        )
        assert params["temperature"] == -0.5

    def test_top_p_negative(self):
        params = anthropic_compat._convert_params(
            {"max_tokens": 128, "top_p": -1.0}
        )
        assert params["top_p"] == -1.0

    def test_top_p_above_one(self):
        params = anthropic_compat._convert_params(
            {"max_tokens": 128, "top_p": 1.5}
        )
        assert params["top_p"] == 1.5

    def test_top_k_negative(self):
        params = anthropic_compat._convert_params(
            {"max_tokens": 128, "top_k": -10}
        )
        assert params["top_k"] == -10

    def test_top_k_very_large(self):
        params = anthropic_compat._convert_params(
            {"max_tokens": 128, "top_k": 1000000}
        )
        assert params["top_k"] == 1000000

    def test_responses_temperature_two(self):
        body = {"model": "m", "input": "hi", "temperature": 2.0}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["temperature"] == 2.0

    def test_responses_negative_top_p(self):
        body = {"model": "m", "input": "hi", "top_p": -0.5}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["top_p"] == -0.5

    def test_responses_max_output_tokens_zero(self):
        """max_output_tokens=0 passes through (backend validates)."""
        body = {"model": "m", "input": "hi", "max_output_tokens": 0}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["max_tokens"] == 0

    def test_responses_max_output_tokens_negative(self):
        body = {"model": "m", "input": "hi", "max_output_tokens": -10}
        openai_body = responses_compat._build_openai_body(body)
        assert openai_body["max_tokens"] == -10


# ---------------------------------------------------------------------------
# System message edge cases
# ---------------------------------------------------------------------------


class TestSystemMessageEdgeCases:
    """Additional edge cases for system message handling."""

    def test_system_none(self):
        """system: null produces no system message."""
        body = {"system": None, "messages": [{"role": "user", "content": "hi"}]}
        msgs = anthropic_compat._convert_messages(body)
        roles = [m["role"] for m in msgs]
        assert "system" not in roles

    def test_system_false(self):
        """system: false (boolean) is falsy, no system message."""
        body = {"system": False, "messages": [{"role": "user", "content": "hi"}]}
        msgs = anthropic_compat._convert_messages(body)
        roles = [m["role"] for m in msgs]
        assert "system" not in roles

    def test_system_zero(self):
        """system: 0 (integer) is falsy, no system message."""
        body = {"system": 0, "messages": [{"role": "user", "content": "hi"}]}
        msgs = anthropic_compat._convert_messages(body)
        roles = [m["role"] for m in msgs]
        assert "system" not in roles

    def test_system_array_with_only_non_text_blocks(self):
        body = {
            "system": [
                {"type": "image", "source": {"type": "base64", "data": "abc"}},
                {"type": "unknown", "content": "ignored"},
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        roles = [m["role"] for m in msgs]
        assert "system" not in roles

    def test_system_array_mixed_text_and_non_text(self):
        body = {
            "system": [
                {"type": "text", "text": "You are helpful."},
                {"type": "cache_control", "control": "ephemeral"},
                {"type": "text", "text": "Be concise."},
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }
        msgs = anthropic_compat._convert_messages(body)
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are helpful.\nBe concise."


# ---------------------------------------------------------------------------
# Tool names with special characters
# ---------------------------------------------------------------------------


class TestToolNameSpecialCharacters:
    """Tool names with special characters should pass through unchanged."""

    def test_anthropic_tool_with_unicode_name(self):
        body = {
            "tools": [{
                "name": "büsqueda_web",
                "description": "Search the web",
                "input_schema": {"type": "object"},
            }],
        }
        tools = anthropic_compat._convert_tools(body)
        assert tools[0]["function"]["name"] == "büsqueda_web"

    def test_anthropic_tool_with_slashes(self):
        body = {
            "tools": [{
                "name": "math/calculate",
                "description": "Do math",
                "input_schema": {},
            }],
        }
        tools = anthropic_compat._convert_tools(body)
        assert tools[0]["function"]["name"] == "math/calculate"

    def test_anthropic_tool_with_dots(self):
        body = {
            "tools": [{
                "name": "api.v2.search",
                "description": "API search",
                "input_schema": {},
            }],
        }
        tools = anthropic_compat._convert_tools(body)
        assert tools[0]["function"]["name"] == "api.v2.search"

    def test_anthropic_tool_with_dashes_and_underscores(self):
        body = {
            "tools": [{
                "name": "my-tool_v2_beta",
                "description": "A tool",
                "input_schema": {},
            }],
        }
        tools = anthropic_compat._convert_tools(body)
        assert tools[0]["function"]["name"] == "my-tool_v2_beta"

    def test_responses_tool_with_unicode_name(self):
        body = {
            "tools": [{
                "type": "function",
                "name": "検索_tool",
                "description": "Search",
                "parameters": {},
            }],
        }
        tools = responses_compat._convert_tools(body)
        assert tools[0]["function"]["name"] == "検索_tool"

    def test_anthropic_tool_empty_name(self):
        """Empty tool name should not crash."""
        body = {
            "tools": [{
                "name": "",
                "description": "Empty name",
                "input_schema": {},
            }],
        }
        tools = anthropic_compat._convert_tools(body)
        assert tools[0]["function"]["name"] == ""

    def test_tool_name_in_response_preserves_special_chars(self):
        """Tool names in response content blocks preserve special chars."""
        result = openai_result(content=None, tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "api.v2/büsqueda",
                "arguments": '{"q": "test"}',
            },
        }], finish_reason="tool_calls")
        blocks = anthropic_compat._build_content_blocks(result)
        tool_block = [b for b in blocks if b["type"] == "tool_use"][0]
        assert tool_block["name"] == "api.v2/büsqueda"


# ---------------------------------------------------------------------------
# Multiple identical tools in one response
# ---------------------------------------------------------------------------


class TestMultipleToolCallsUniqueIds:
    """Multiple tool calls should each have a unique ID."""

    def test_anthropic_multiple_same_tool_unique_ids(self):
        result = openai_result(content=None, tool_calls=[
            {
                "id": "call_aaa",
                "type": "function",
                "function": {"name": "search", "arguments": '{"q": "a"}'},
            },
            {
                "id": "call_bbb",
                "type": "function",
                "function": {"name": "search", "arguments": '{"q": "b"}'},
            },
            {
                "id": "call_ccc",
                "type": "function",
                "function": {"name": "search", "arguments": '{"q": "c"}'},
            },
        ], finish_reason="tool_calls")
        blocks = anthropic_compat._build_content_blocks(result)
        tool_ids = [b["id"] for b in blocks if b["type"] == "tool_use"]
        assert len(tool_ids) == 3
        assert len(set(tool_ids)) == 3  # All unique

    def test_responses_multiple_same_tool_unique_ids(self):
        result = openai_result(content=None, tool_calls=[
            {
                "id": "call_111",
                "type": "function",
                "function": {"name": "search", "arguments": '{"q": "x"}'},
            },
            {
                "id": "call_222",
                "type": "function",
                "function": {"name": "search", "arguments": '{"q": "y"}'},
            },
        ], finish_reason="tool_calls")
        output = responses_compat._build_output_items(result)
        func_items = [o for o in output if o["type"] == "function_call"]
        ids = [f["id"] for f in func_items]
        call_ids = [f["call_id"] for f in func_items]
        assert len(set(ids)) == 2
        assert len(set(call_ids)) == 2
        # id and call_id should match for each item
        for f in func_items:
            assert f["id"] == f["call_id"]

    def test_anthropic_tool_calls_with_no_ids_get_generated(self):
        """Tool calls without IDs should get auto-generated unique IDs."""
        result = openai_result(content=None, tool_calls=[
            {
                "type": "function",
                "function": {"name": "tool_a", "arguments": "{}"},
            },
            {
                "type": "function",
                "function": {"name": "tool_b", "arguments": "{}"},
            },
        ], finish_reason="tool_calls")
        blocks = anthropic_compat._build_content_blocks(result)
        tool_ids = [b["id"] for b in blocks if b["type"] == "tool_use"]
        assert len(tool_ids) == 2
        assert all(id.startswith("toolu_") for id in tool_ids)
        assert tool_ids[0] != tool_ids[1]


# ---------------------------------------------------------------------------
# Large message arrays (performance sanity)
# ---------------------------------------------------------------------------


class TestLargeMessageArray:
    """Large conversation histories should convert without error."""

    def test_anthropic_1000_messages(self):
        messages = []
        for i in range(500):
            messages.append({"role": "user", "content": f"Message {i}"})
            messages.append({"role": "assistant", "content": f"Reply {i}"})

        body = {
            "model": "test",
            "max_tokens": 128,
            "messages": messages,
        }
        err = anthropic_compat._validate_request(body)
        assert err is None

        openai_body = anthropic_compat._build_openai_body(body)
        # 1000 messages + no system = 1000
        assert len(openai_body["messages"]) == 1000

    def test_responses_1000_input_items(self):
        items = []
        for i in range(1000):
            items.append({
                "type": "message",
                "role": "user",
                "content": f"Turn {i}",
            })
        body = {"model": "test", "input": items}
        openai_body = responses_compat._build_openai_body(body)
        assert len(openai_body["messages"]) == 1000


# ---------------------------------------------------------------------------
# Anthropic: user message content edge cases
# ---------------------------------------------------------------------------


class TestUserMessageContentEdgeCases:
    """Edge cases in user message content handling."""

    def test_empty_content_list_produces_no_messages(self):
        """Content as empty array produces no messages for this user turn."""
        result = anthropic_compat._convert_user_message([])
        assert result == []

    def test_content_with_only_unknown_blocks(self):
        result = anthropic_compat._convert_user_message([
            {"type": "video", "data": "..."},
            {"type": "audio", "data": "..."},
        ])
        assert result == []

    def test_content_as_none(self):
        """None content is coerced to string 'None'."""
        result = anthropic_compat._convert_user_message(None)
        assert len(result) == 1
        assert result[0]["content"] == "None"

    def test_content_as_integer(self):
        result = anthropic_compat._convert_user_message(42)
        assert result[0]["content"] == "42"

    def test_content_as_boolean(self):
        result = anthropic_compat._convert_user_message(True)
        assert result[0]["content"] == "True"

    def test_content_with_mixed_known_and_unknown_blocks(self):
        """Known blocks extracted, unknown blocks ignored."""
        result = anthropic_compat._convert_user_message([
            {"type": "text", "text": "Hello"},
            {"type": "video", "data": "..."},
            {"type": "text", "text": "World"},
        ])
        assert len(result) == 1
        assert result[0]["role"] == "user"
        content = result[0]["content"]
        if isinstance(content, list):
            texts = [p["text"] for p in content if p.get("type") == "text"]
            assert "Hello" in texts
            assert "World" in texts
        else:
            assert "Hello" in content
            assert "World" in content


# ---------------------------------------------------------------------------
# Anthropic: assistant message edge cases
# ---------------------------------------------------------------------------


class TestAssistantMessageEdgeCases:
    """Edge cases in assistant message content handling."""

    def test_thinking_only_blocks_stripped(self):
        result = anthropic_compat._convert_assistant_message([
            {"type": "thinking", "thinking": "Let me think..."},
        ])
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] is None
        assert "tool_calls" not in result[0]

    def test_empty_content_list(self):
        result = anthropic_compat._convert_assistant_message([])
        assert len(result) == 1
        assert result[0]["content"] is None

    def test_tool_use_without_input(self):
        """tool_use block with no input key defaults to empty dict."""
        result = anthropic_compat._convert_assistant_message([
            {"type": "tool_use", "id": "toolu_1", "name": "my_tool"},
        ])
        assert len(result) == 1
        tc = result[0]["tool_calls"][0]
        assert tc["function"]["arguments"] == "{}"

    def test_tool_use_with_none_input(self):
        """tool_use block with input=None."""
        result = anthropic_compat._convert_assistant_message([
            {"type": "tool_use", "id": "toolu_2", "name": "my_tool", "input": None},
        ])
        tc = result[0]["tool_calls"][0]
        assert tc["function"]["arguments"] == "null"


# ---------------------------------------------------------------------------
# Responses API: input edge cases
# ---------------------------------------------------------------------------


class TestResponsesInputEdgeCases:
    """Edge cases in Responses API input conversion."""

    def test_input_empty_array(self):
        """Empty input array produces no messages."""
        msgs = responses_compat._convert_input_to_messages({"input": []})
        assert msgs == []

    def test_input_empty_array_with_instructions(self):
        """Empty input array with instructions produces system message only."""
        msgs = responses_compat._convert_input_to_messages({
            "instructions": "Be helpful",
            "input": [],
        })
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"

    def test_input_integer(self):
        msgs = responses_compat._convert_input_to_messages({"input": 42})
        assert msgs[0]["content"] == "42"

    def test_input_boolean(self):
        msgs = responses_compat._convert_input_to_messages({"input": True})
        assert msgs[0]["content"] == "True"

    def test_input_array_of_mixed_types(self):
        """Array with strings, dicts, numbers."""
        msgs = responses_compat._convert_input_to_messages({"input": [
            "hello",
            42,
            {"type": "message", "role": "user", "content": "world"},
        ]})
        assert len(msgs) == 3
        assert msgs[0]["content"] == "hello"
        assert msgs[1]["content"] == "42"
        assert msgs[2]["content"] == "world"

    def test_function_call_without_call_id_or_id(self):
        """function_call with no ID fields."""
        msgs = responses_compat._convert_input_to_messages({"input": [
            {"type": "function_call", "name": "my_func", "arguments": "{}"},
        ]})
        assert len(msgs) == 1
        tc = msgs[0]["tool_calls"][0]
        assert tc["id"] == ""

    def test_function_call_output_without_output(self):
        msgs = responses_compat._convert_input_to_messages({"input": [
            {"type": "function_call_output", "call_id": "call_x"},
        ]})
        assert msgs[0]["content"] == ""


# ---------------------------------------------------------------------------
# Responses API: content parts edge cases
# ---------------------------------------------------------------------------


class TestContentPartsEdgeCases:
    """Edge cases in Responses API content part conversion."""

    def test_input_file_with_filename(self):
        parts = [{"type": "input_file", "filename": "report.pdf"}]
        result = responses_compat._convert_content_parts(parts)
        assert "report.pdf" in result

    def test_input_file_without_filename(self):
        parts = [{"type": "input_file"}]
        result = responses_compat._convert_content_parts(parts)
        assert "[Attached file]" in result

    def test_unknown_part_type_with_text_field(self):
        parts = [{"type": "custom_widget", "text": "widget data"}]
        result = responses_compat._convert_content_parts(parts)
        assert "widget data" in result

    def test_non_dict_part(self):
        parts = ["just a string", 42]
        result = responses_compat._convert_content_parts(parts)
        assert "just a string" in result
        assert "42" in result


# ---------------------------------------------------------------------------
# Tool choice edge cases
# ---------------------------------------------------------------------------


class TestToolChoiceEdgeCases:
    """Edge cases in tool_choice conversion."""

    def test_anthropic_tool_choice_tool_without_name(self):
        body = {"tool_choice": {"type": "tool"}}
        result = anthropic_compat._convert_tool_choice(body)
        assert result == {"type": "function", "function": {"name": ""}}

    def test_anthropic_tool_choice_unknown_type(self):
        body = {"tool_choice": {"type": "custom_type"}}
        result = anthropic_compat._convert_tool_choice(body)
        assert result is None

    def test_anthropic_tool_choice_string(self):
        """tool_choice as a string (not an object) should return None safely.
        Previously crashed with AttributeError because str has no .get() method."""
        body = {"tool_choice": "auto"}
        result = anthropic_compat._convert_tool_choice(body)
        assert result is None

    def test_responses_tool_choice_dict_unknown_type(self):
        body = {"tool_choice": {"type": "my_custom_tool"}}
        result = responses_compat._convert_tool_choice(body)
        # Unknown dict type returns None
        assert result is None


# ---------------------------------------------------------------------------
# Anthropic: tool_choice as plain string
# ---------------------------------------------------------------------------


class TestAnthropicToolChoiceAsString:
    """Anthropic tool_choice should be a dict but clients might send strings."""

    def test_string_auto(self):
        """tool_choice: 'auto' (string, not dict) should not crash."""
        body = {"tool_choice": "auto"}
        # str doesn't have .get(), so this would crash with AttributeError
        # Let's verify current behavior
        try:
            result = anthropic_compat._convert_tool_choice(body)
            # If it succeeds, the function handled it
        except AttributeError:
            pytest.fail("_convert_tool_choice crashed on string tool_choice")

    def test_string_none_value(self):
        body = {"tool_choice": "none"}
        try:
            result = anthropic_compat._convert_tool_choice(body)
        except AttributeError:
            pytest.fail("_convert_tool_choice crashed on string tool_choice='none'")

    def test_integer_tool_choice(self):
        """Degenerate tool_choice value should not crash."""
        body = {"tool_choice": 42}
        try:
            result = anthropic_compat._convert_tool_choice(body)
        except (AttributeError, TypeError):
            pytest.fail("_convert_tool_choice crashed on integer tool_choice")


# ---------------------------------------------------------------------------
# Streaming: tool ID normalization consistency
# ---------------------------------------------------------------------------


class TestStreamingToolIdNormalization:
    """Tool IDs should be correctly normalized in streaming events."""

    @pytest.mark.asyncio
    async def test_anthropic_streaming_tool_id_normalized_to_toolu(self):
        """Tool call ID in streaming should be normalized to toolu_ prefix."""
        chunks = [
            sse_chunk({
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "id": "call_abc123",
                            "function": {"name": "my_tool", "arguments": ""},
                        }],
                    },
                    "index": 0,
                }],
            }),
            sse_chunk({
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "function": {"arguments": '{"x":1}'},
                        }],
                    },
                    "index": 0,
                }],
            }),
            sse_chunk({
                "choices": [{
                    "delta": {},
                    "finish_reason": "tool_calls",
                    "index": 0,
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }),
            "data: [DONE]\n\n",
        ]

        async def gen():
            for c in chunks:
                yield c

        events = []
        async for event in anthropic_compat._anthropic_stream_converter(
            gen(), "test-model"
        ):
            events.append(event)

        sse_events = parse_anthropic_sse_events("".join(events))
        tool_start = [e for e in sse_events if e.get("type") == "content_block_start"
                      and e.get("content_block", {}).get("type") == "tool_use"]
        assert len(tool_start) == 1
        assert tool_start[0]["content_block"]["id"].startswith("toolu_")
        assert "abc123" in tool_start[0]["content_block"]["id"]


# ---------------------------------------------------------------------------
# Integration: max_tokens=0 rejected at route level
# ---------------------------------------------------------------------------


class TestMaxTokensZeroIntegration:
    """Integration test: max_tokens=0 should be rejected by the route handler."""

    def test_anthropic_max_tokens_zero(self, monkeypatch):
        app = make_anthropic_app()
        client = make_client(app)
        # No need to mock LLM since validation should reject before reaching it
        resp = client.post("/v1/messages", json={
            "model": "test",
            "max_tokens": 0,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 400
        body = resp.json()
        assert "positive" in body["error"]["message"]

    def test_anthropic_max_tokens_negative(self, monkeypatch):
        app = make_anthropic_app()
        client = make_client(app)
        resp = client.post("/v1/messages", json={
            "model": "test",
            "max_tokens": -5,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 400

    def test_anthropic_max_tokens_string(self, monkeypatch):
        app = make_anthropic_app()
        client = make_client(app)
        resp = client.post("/v1/messages", json={
            "model": "test",
            "max_tokens": "not-a-number",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Anthropic: tool_choice string handling fix
# ---------------------------------------------------------------------------


class TestAnthropicToolChoiceStringFix:
    """Verify _convert_tool_choice handles non-dict values safely."""

    def test_list_tool_choice(self):
        """tool_choice as a list should return None safely."""
        body = {"tool_choice": ["auto"]}
        result = anthropic_compat._convert_tool_choice(body)
        assert result is None

    def test_true_tool_choice(self):
        body = {"tool_choice": True}
        result = anthropic_compat._convert_tool_choice(body)
        assert result is None

    def test_empty_dict_tool_choice(self):
        body = {"tool_choice": {}}
        result = anthropic_compat._convert_tool_choice(body)
        # type is None, no match -> returns None
        assert result is None


# ---------------------------------------------------------------------------
# Responses API: tool_choice edge cases
# ---------------------------------------------------------------------------


class TestResponsesToolChoiceEdgeCases:

    def test_string_auto(self):
        body = {"tool_choice": "auto"}
        result = responses_compat._convert_tool_choice(body)
        assert result == "auto"

    def test_string_none(self):
        body = {"tool_choice": "none"}
        result = responses_compat._convert_tool_choice(body)
        assert result == "none"

    def test_string_required(self):
        body = {"tool_choice": "required"}
        result = responses_compat._convert_tool_choice(body)
        assert result == "required"

    def test_dict_function_no_name(self):
        body = {"tool_choice": {"type": "function"}}
        result = responses_compat._convert_tool_choice(body)
        assert result == {"type": "function", "function": {"name": ""}}

    def test_integer_tool_choice(self):
        body = {"tool_choice": 42}
        result = responses_compat._convert_tool_choice(body)
        assert result is None

    def test_empty_string_tool_choice(self):
        """Empty string is falsy in Python -> tc is '', isinstance(tc, str) is True."""
        body = {"tool_choice": ""}
        result = responses_compat._convert_tool_choice(body)
        # "" is a string, so it passes through (OpenAI Chat Completions would reject)
        assert result == ""


# ---------------------------------------------------------------------------
# Responses API: _build_responses_response without request_body
# ---------------------------------------------------------------------------


class TestBuildResponseNoRequestBody:
    """_build_responses_response should work when request_body is None."""

    def test_no_request_body(self):
        result = openai_result()
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_123"
        )
        assert resp["metadata"] == {}
        assert resp["truncation"] == "disabled"
        assert resp["parallel_tool_calls"] is True
        assert resp["instructions"] is None

    def test_request_body_with_none_metadata(self):
        result = openai_result()
        resp = responses_compat._build_responses_response(
            result, "test-model", "resp_123",
            request_body={"metadata": None},
        )
        assert resp["metadata"] == {}


# ---------------------------------------------------------------------------
# SSE event formatting with special characters
# ---------------------------------------------------------------------------


class TestSSEEventSpecialCharacters:
    """SSE events should correctly escape special characters in JSON."""

    def test_newlines_in_content(self):
        event = sse_event("test", {"text": "line1\nline2\nline3"})
        assert "\\n" in event  # JSON-escaped newlines
        data = json.loads(event.split("data: ")[1].strip())
        assert data["text"] == "line1\nline2\nline3"

    def test_unicode_in_event_data(self):
        event = sse_event("test", {"text": "你好世界"})
        data = json.loads(event.split("data: ")[1].strip())
        assert data["text"] == "你好世界"

    def test_backslash_in_content(self):
        event = sse_event("test", {"path": "C:\\Users\\test"})
        data = json.loads(event.split("data: ")[1].strip())
        assert data["path"] == "C:\\Users\\test"

    def test_quotes_in_content(self):
        event = sse_event("test", {"text": 'He said "hello"'})
        data = json.loads(event.split("data: ")[1].strip())
        assert data["text"] == 'He said "hello"'


# ---------------------------------------------------------------------------
# Tool ID normalization edge cases
# ---------------------------------------------------------------------------


class TestToolIdNormalizationEdgeCases:
    """Edge cases in tool ID prefix normalization."""

    def test_empty_string(self):
        assert to_anthropic_tool_id("") == ""
        assert to_openai_tool_id("") == ""

    def test_double_prefix_not_stacked(self):
        """Already-prefixed IDs should not get double-prefixed."""
        assert to_anthropic_tool_id("toolu_abc") == "toolu_abc"
        assert to_openai_tool_id("call_abc") == "call_abc"

    def test_cross_prefix_conversion(self):
        assert to_anthropic_tool_id("call_xyz") == "toolu_xyz"
        assert to_openai_tool_id("toolu_xyz") == "call_xyz"

    def test_bare_id_gets_prefix(self):
        assert to_anthropic_tool_id("my_id_123") == "toolu_my_id_123"
        assert to_openai_tool_id("my_id_123") == "call_my_id_123"

    def test_chatcmpl_prefix_stripped(self):
        assert to_anthropic_tool_id("chatcmpl-xyz123") == "toolu_xyz123"
        assert to_openai_tool_id("chatcmpl-xyz123") == "call_xyz123"

    def test_unicode_id(self):
        assert to_anthropic_tool_id("call_élève") == "toolu_élève"
        assert to_openai_tool_id("toolu_élève") == "call_élève"


# ---------------------------------------------------------------------------
# Anthropic: model is falsy but present
# ---------------------------------------------------------------------------


class TestModelFalsyValues:
    """model field with falsy values should be rejected."""

    def test_model_empty_string_rejected(self):
        resp = anthropic_compat._validate_request({
            "model": "",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp is not None
        assert resp.status_code == 400

    def test_model_none_rejected(self):
        resp = anthropic_compat._validate_request({
            "model": None,
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp is not None
        assert resp.status_code == 400

    def test_model_zero_rejected(self):
        resp = anthropic_compat._validate_request({
            "model": 0,
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp is not None
        assert resp.status_code == 400

    def test_responses_model_empty_rejected(self, monkeypatch):
        app = make_responses_app()
        client = make_client(app)
        resp = client.post("/v1/responses", json={
            "model": "",
            "input": "hello",
        })
        assert resp.status_code == 400


if __name__ == "__main__":
    unittest.main()
