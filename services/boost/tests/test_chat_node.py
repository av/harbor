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


class TestChatNodeContent:
    def test_text_only_content_parts_flatten_to_text(self):
        node = ChatNode.from_message({
            "role": "user",
            "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ],
        })

        assert node.content == "first\nsecond"

    def test_multimodal_content_parts_are_preserved(self):
        content = [
            {"type": "text", "text": "describe this image"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]

        node = ChatNode.from_message({"role": "user", "content": content})

        assert node.content is content
