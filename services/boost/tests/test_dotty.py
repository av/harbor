"""Unit tests for the dotty module (dot-notation dict/list/attr access)."""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import dotty


# ---------------------------------------------------------------------------
# parse_path
# ---------------------------------------------------------------------------

class TestParsePath:
    def test_simple_key(self):
        assert dotty.parse_path("a") == ["a"]

    def test_dotted_path(self):
        assert dotty.parse_path("a.b.c") == ["a", "b", "c"]

    def test_integer_key(self):
        assert dotty.parse_path("0") == [0]

    def test_mixed_string_and_int(self):
        assert dotty.parse_path("a.0.b") == ["a", 0, "b"]

    def test_bracket_notation(self):
        assert dotty.parse_path("a[0]") == ["a", 0]

    def test_bracket_with_string(self):
        assert dotty.parse_path("a[key]") == ["a", "key"]

    def test_mixed_dot_and_bracket(self):
        assert dotty.parse_path("a.b[0].c") == ["a", "b", 0, "c"]

    def test_negative_index_dot(self):
        assert dotty.parse_path("a.-1") == ["a", -1]

    def test_negative_index_bracket(self):
        assert dotty.parse_path("a[-1]") == ["a", -1]

    def test_empty_string(self):
        assert dotty.parse_path("") == []

    def test_none(self):
        assert dotty.parse_path(None) == []

    def test_list_input(self):
        assert dotty.parse_path(["a", 0, "b"]) == ["a", 0, "b"]

    def test_tuple_input(self):
        assert dotty.parse_path(("x", 1)) == ["x", 1]


# ---------------------------------------------------------------------------
# is_int
# ---------------------------------------------------------------------------

class TestIsInt:
    def test_positive_integer(self):
        assert dotty.is_int(42) is True

    def test_zero(self):
        assert dotty.is_int(0) is True

    def test_negative_integer(self):
        assert dotty.is_int(-1) is True

    def test_digit_string(self):
        assert dotty.is_int("3") is True

    def test_negative_digit_string(self):
        assert dotty.is_int("-5") is True

    def test_empty_string(self):
        assert dotty.is_int("") is False

    def test_minus_only(self):
        assert dotty.is_int("-") is False

    def test_alpha_string(self):
        assert dotty.is_int("abc") is False

    def test_float(self):
        assert dotty.is_int(3.14) is False

    def test_none(self):
        assert dotty.is_int(None) is False

    def test_list(self):
        assert dotty.is_int([1]) is False


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

class TestGet:
    def test_simple_key(self):
        assert dotty.get({"a": 1}, "a") == 1

    def test_nested_key(self):
        assert dotty.get({"a": {"b": 2}}, "a.b") == 2

    def test_deeply_nested(self):
        obj = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        assert dotty.get(obj, "a.b.c.d.e") == "deep"

    def test_list_index(self):
        assert dotty.get({"a": [10, 20, 30]}, "a.1") == 20

    def test_bracket_list_index(self):
        assert dotty.get({"items": [10, 20]}, "items[1]") == 20

    def test_negative_list_index(self):
        assert dotty.get({"a": ["x", "y", "z"]}, "a.-1") == "z"

    def test_missing_key_returns_default(self):
        assert dotty.get({"a": 1}, "b") is None

    def test_missing_key_custom_default(self):
        assert dotty.get({"a": 1}, "b", "fallback") == "fallback"

    def test_missing_nested_returns_default(self):
        assert dotty.get({"a": {}}, "a.b.c", "nope") == "nope"

    def test_none_obj_returns_default(self):
        assert dotty.get(None, "a", "default") == "default"

    def test_none_value_returns_default(self):
        # Intentional behavior: None values are treated as missing
        assert dotty.get({"a": None}, "a", "default") == "default"

    def test_none_value_no_default(self):
        assert dotty.get({"a": None}, "a") is None

    def test_out_of_bounds_list(self):
        assert dotty.get({"a": [1]}, "a.5", "oob") == "oob"

    def test_string_key_on_list(self):
        assert dotty.get(["a", "b"], "foo", "nope") == "nope"

    def test_int_key_on_dict(self):
        # When dict has int key 0, parse_path("0") -> [0]
        assert dotty.get({0: "zero"}, "0") == "zero"

    def test_empty_path(self):
        obj = {"a": 1}
        assert dotty.get(obj, "") == obj

    def test_nested_none_intermediate(self):
        assert dotty.get({"a": None}, "a.b", "default") == "default"

    def test_choices_0_message_pattern(self):
        """The most common access pattern in the codebase."""
        result = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        assert dotty.get(result, "choices.0.message") == {"content": "hello"}
        assert dotty.get(result, "choices.0.message.content") == "hello"
        assert dotty.get(result, "choices.0.finish_reason") == "stop"
        assert dotty.get(result, "usage") == {"prompt_tokens": 10, "completion_tokens": 5}

    def test_choices_0_message_missing(self):
        assert dotty.get({}, "choices.0.message", {}) == {}
        assert dotty.get({"choices": []}, "choices.0.message", {}) == {}

    def test_attribute_access(self):
        class Obj:
            x = 42
        assert dotty.get(Obj(), "x") == 42

    def test_property_access(self):
        class Obj:
            @property
            def val(self):
                return "prop"
        assert dotty.get(Obj(), "val") == "prop"


# ---------------------------------------------------------------------------
# set
# ---------------------------------------------------------------------------

class TestSet:
    def test_simple_set(self):
        obj = {}
        dotty.set(obj, "a", 1)
        assert obj == {"a": 1}

    def test_nested_set(self):
        obj = {}
        dotty.set(obj, "a.b.c", 42)
        assert obj == {"a": {"b": {"c": 42}}}

    def test_overwrite_existing(self):
        obj = {"a": {"b": 1}}
        dotty.set(obj, "a.b", 2)
        assert obj["a"]["b"] == 2

    def test_create_intermediate_list(self):
        obj = {}
        dotty.set(obj, "a.0.name", "first")
        assert obj == {"a": [{"name": "first"}]}

    def test_set_on_none_obj(self):
        result = dotty.set(None, "a", 1)
        assert result == {"a": 1}

    def test_empty_path_replaces_root(self):
        result = dotty.set({"a": 1}, "", "replaced")
        assert result == "replaced"

    def test_extend_list(self):
        obj = {"items": []}
        dotty.set(obj, "items.0", "a")
        assert obj == {"items": ["a"]}

    def test_extend_list_with_gap(self):
        obj = {"items": []}
        dotty.set(obj, "items.2", "c")
        assert obj == {"items": [None, None, "c"]}

    def test_returns_obj(self):
        obj = {"x": 1}
        result = dotty.set(obj, "y", 2)
        assert result is obj


# ---------------------------------------------------------------------------
# has
# ---------------------------------------------------------------------------

class TestHas:
    def test_existing_key(self):
        assert dotty.has({"a": 1}, "a") is True

    def test_missing_key(self):
        assert dotty.has({"a": 1}, "b") is False

    def test_nested_existing(self):
        assert dotty.has({"a": {"b": 2}}, "a.b") is True

    def test_nested_missing(self):
        assert dotty.has({"a": {"b": 2}}, "a.c") is False

    def test_list_in_bounds(self):
        assert dotty.has({"a": [1, 2]}, "a.0") is True

    def test_list_out_of_bounds(self):
        assert dotty.has({"a": [1]}, "a.5") is False

    def test_none_obj(self):
        assert dotty.has(None, "a") is False

    def test_empty_path(self):
        assert dotty.has({"a": 1}, "") is False

    def test_none_value_exists(self):
        # None values DO exist (has checks existence, not truthiness)
        assert dotty.has({"a": None}, "a") is True

    def test_beyond_leaf(self):
        assert dotty.has({"a": 1}, "a.b") is False

    def test_choices_0_message_pattern(self):
        result = {"choices": [{"message": {"content": "hi"}}]}
        assert dotty.has(result, "choices.0.message.content") is True
        assert dotty.has(result, "choices.0.message.tool_calls") is False
        assert dotty.has(result, "choices.1") is False


# ---------------------------------------------------------------------------
# Integration: realistic codebase access patterns
# ---------------------------------------------------------------------------

class TestCodebasePatterns:
    """Test patterns actually used in anthropic_compat.py and responses_compat.py."""

    def test_openai_result_full(self):
        openai_result = {
            "id": "chatcmpl-abc",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello!",
                    "tool_calls": None,
                    "refusal": None,
                },
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }
        assert dotty.get(openai_result, "choices.0.message", {}) == openai_result["choices"][0]["message"]
        assert dotty.get(openai_result, "choices.0.message.content") == "Hello!"
        # tool_calls is None -> returns default []
        assert dotty.get(openai_result, "choices.0.message.tool_calls", []) == []
        assert dotty.get(openai_result, "choices.0.finish_reason", "stop") == "stop"
        assert dotty.get(openai_result, "usage", {}) == openai_result["usage"]

    def test_openai_result_with_tools(self):
        openai_result = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "call_1", "function": {"name": "search", "arguments": "{}"}},
                    ],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        }
        # content is None -> returns default (None, which is falsy)
        content = dotty.get(openai_result, "choices.0.message.content")
        assert not content
        # tool_calls exist
        tool_calls = dotty.get(openai_result, "choices.0.message.tool_calls", [])
        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "search"

    def test_empty_result(self):
        assert dotty.get({}, "choices.0.message", {}) == {}
        assert dotty.get({}, "choices.0.message.content") is None
        assert dotty.get({}, "choices.0.finish_reason", "stop") == "stop"

    def test_reasoning_tokens_deep_path(self):
        result = {
            "usage": {
                "completion_tokens_details": {
                    "reasoning_tokens": 100,
                }
            }
        }
        tokens = dotty.get(result, "usage.completion_tokens_details.reasoning_tokens", 0)
        assert tokens == 100

    def test_reasoning_tokens_missing(self):
        result = {"usage": {"prompt_tokens": 5}}
        tokens = dotty.get(result, "usage.completion_tokens_details.reasoning_tokens", 0)
        assert tokens == 0
