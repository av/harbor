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


def test_history_merges_consecutive_same_role_plain_messages():
    tail = ChatNode.from_conversation([
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "intro"},
        {"role": "assistant", "content": "step 1"},
        {"role": "assistant", "content": ""},
    ])

    assert tail.history() == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "intro\n\nstep 1"},
    ]


def test_history_merge_skips_tool_messages():
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "f", "arguments": "{}"},
    }
    tail = ChatNode.from_conversation([
        {"role": "assistant", "content": "plain"},
        {"role": "assistant", "content": "", "tool_calls": [tool_call]},
        {"role": "tool", "tool_call_id": "call_1", "content": "a"},
        {"role": "tool", "tool_call_id": "call_2", "content": "b"},
    ])

    history = tail.history()
    assert len(history) == 4
    assert history[1]["tool_calls"] == [tool_call]
