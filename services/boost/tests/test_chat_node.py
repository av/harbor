"""Tests for Boost chat history nodes."""

from chat_node import ChatNode


def test_from_conversation_preserves_tool_metadata():
    tail = ChatNode.from_conversation([
        {"role": "user", "content": "check weather"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_123",
                "type": "function",
                "function": {"name": "weather", "arguments": "{\"city\":\"Paris\"}"},
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "call_123",
            "content": "Sunny",
        },
    ])

    assert tail.history() == [
        {"role": "user", "content": "check weather"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_123",
                "type": "function",
                "function": {"name": "weather", "arguments": "{\"city\":\"Paris\"}"},
            }],
        },
        {
            "role": "tool",
            "content": "Sunny",
            "tool_call_id": "call_123",
        },
    ]
