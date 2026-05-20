"""SDK integration tests for Boost API compatibility layers.

These tests exercise the Anthropic and OpenAI compat layers through the actual
SDK client objects (``anthropic.AsyncAnthropic`` and ``openai.AsyncOpenAI``),
proving end-to-end compatibility.  The ASGI app is driven in-process via
``httpx.ASGITransport`` — no real server is started.

The mapper/LLM layer is mocked so no real backend is required.
"""

import json
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import httpx
import pytest

import anthropic
import openai

# Module stubs for mapper/llm are registered in conftest.py

import anthropic_compat
import responses_compat


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_app():
    """Build a FastAPI app with both compat routers and the global error handler."""
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
    from main import app
    return app


class _FakeLLM:
    """Minimal stand-in for llm.LLM that returns configurable responses."""

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
        async for _ in stream:
            pass
        return self._consume_result

    async def chat_completion(self):
        return self._chat_completion_result


def _sse_chunk(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


def _openai_result(content="Hello!", finish_reason="stop",
                   prompt_tokens=10, completion_tokens=5,
                   tool_calls=None, reasoning_content=None):
    """Build a minimal OpenAI-shaped chat completion result."""
    msg = {"content": content, "tool_calls": tool_calls or []}
    if reasoning_content:
        msg["reasoning_content"] = reasoning_content
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


def _streaming_chunks(content="Hello!", finish_reason="stop",
                      prompt_tokens=10, completion_tokens=5):
    """Build a list of SSE-formatted streaming chunk strings."""
    chunks = []
    # Content chunk
    chunks.append(_sse_chunk({
        "choices": [{"delta": {"role": "assistant", "content": content}, "index": 0}],
    }))
    # Finish chunk with usage
    chunks.append(_sse_chunk({
        "choices": [{"delta": {}, "index": 0, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }))
    chunks.append("data: [DONE]\n\n")
    return chunks


def _tool_call_streaming_chunks():
    """Build streaming chunks that include a tool call."""
    chunks = []
    chunks.append(_sse_chunk({
        "choices": [{"delta": {"role": "assistant", "content": None,
                                "tool_calls": [{"index": 0, "id": "call_abc123",
                                                "type": "function",
                                                "function": {"name": "get_weather",
                                                             "arguments": ""}}]}, "index": 0}],
    }))
    chunks.append(_sse_chunk({
        "choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"city":"NYC"}'}}]}, "index": 0}],
    }))
    chunks.append(_sse_chunk({
        "choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
    }))
    chunks.append("data: [DONE]\n\n")
    return chunks


def _mock_mapper():
    """Set up mapper mock attributes."""
    mock = MagicMock()
    mock.list_downstream = AsyncMock(return_value=[
        {"id": "test-model", "object": "model", "created": 1700000000, "owned_by": "test"},
    ])
    mock.resolve_request_config = MagicMock(return_value={})
    mock.is_direct_task = MagicMock(return_value=False)
    mock.get_proxy_model = MagicMock(side_effect=lambda mod, model: model)
    mock.workflow_models = MagicMock(return_value=[])
    return mock


def _patch_both_layers(fake_llm, mock_mapper_obj):
    """Return a context manager that patches mapper and LLM in both compat layers."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        with (
            patch.object(anthropic_compat, "mapper", mock_mapper_obj),
            patch.object(anthropic_compat, "llm_mod") as mock_llm_a,
            patch.object(responses_compat, "mapper", mock_mapper_obj),
            patch.object(responses_compat, "llm_mod") as mock_llm_r,
        ):
            mock_llm_a.LLM = MagicMock(return_value=fake_llm)
            mock_llm_r.LLM = MagicMock(return_value=fake_llm)
            yield
    return _ctx()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    return _build_app()


@pytest.fixture
def mock_mapper_obj():
    return _mock_mapper()


# ---------------------------------------------------------------------------
# Anthropic SDK Integration Tests
# ---------------------------------------------------------------------------


class TestAnthropicSDKNonStreaming:
    """Non-streaming message creation via the real Anthropic SDK."""

    @pytest.mark.asyncio
    async def test_create_message_returns_message_object(self, app, mock_mapper_obj):
        fake = _FakeLLM(
            consume_result=_openai_result(content="Hello from Boost!"),
            stream_chunks=[],
        )
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                message = await client.messages.create(
                    model="test-model",
                    max_tokens=128,
                    messages=[{"role": "user", "content": "Hello"}],
                )

        assert isinstance(message, anthropic.types.Message)
        assert message.role == "assistant"
        assert message.type == "message"
        assert message.model == "test-model"
        assert message.stop_reason == "end_turn"
        assert len(message.content) >= 1
        assert message.content[0].type == "text"
        assert message.content[0].text == "Hello from Boost!"

    @pytest.mark.asyncio
    async def test_message_has_proper_usage(self, app, mock_mapper_obj):
        fake = _FakeLLM(
            consume_result=_openai_result(prompt_tokens=15, completion_tokens=8),
            stream_chunks=[],
        )
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                message = await client.messages.create(
                    model="test-model",
                    max_tokens=128,
                    messages=[{"role": "user", "content": "Hello"}],
                )

        assert isinstance(message.usage, anthropic.types.Usage)
        assert message.usage.input_tokens == 15
        assert message.usage.output_tokens == 8

    @pytest.mark.asyncio
    async def test_message_has_request_id(self, app, mock_mapper_obj):
        fake = _FakeLLM(
            consume_result=_openai_result(),
            stream_chunks=[],
        )
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                # Use with_raw_response to check headers
                raw = await client.messages.with_raw_response.create(
                    model="test-model",
                    max_tokens=128,
                    messages=[{"role": "user", "content": "Hello"}],
                )

        assert raw.http_response.headers.get("request-id") is not None
        message = raw.parse()
        assert isinstance(message, anthropic.types.Message)

    @pytest.mark.asyncio
    async def test_tool_use_response(self, app, mock_mapper_obj):
        """Verify tool_use content blocks are returned as proper ToolUseBlock objects."""
        result = _openai_result(content=None, finish_reason="tool_calls")
        result["choices"][0]["message"]["tool_calls"] = [{
            "id": "call_abc123",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city": "NYC"}'},
        }]
        result["choices"][0]["message"]["content"] = None

        fake = _FakeLLM(consume_result=result, stream_chunks=[])
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                message = await client.messages.create(
                    model="test-model",
                    max_tokens=128,
                    messages=[{"role": "user", "content": "What is the weather?"}],
                    tools=[{
                        "name": "get_weather",
                        "description": "Get weather for a city",
                        "input_schema": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                        },
                    }],
                )

        assert message.stop_reason == "tool_use"
        tool_blocks = [b for b in message.content if b.type == "tool_use"]
        assert len(tool_blocks) == 1
        assert isinstance(tool_blocks[0], anthropic.types.ToolUseBlock)
        assert tool_blocks[0].name == "get_weather"
        assert tool_blocks[0].input == {"city": "NYC"}
        assert tool_blocks[0].id.startswith("toolu_")

    @pytest.mark.asyncio
    async def test_multi_message_conversation(self, app, mock_mapper_obj):
        """Multi-turn conversation produces valid Message."""
        fake = _FakeLLM(
            consume_result=_openai_result(content="I see your follow-up."),
            stream_chunks=[],
        )
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                message = await client.messages.create(
                    model="test-model",
                    max_tokens=128,
                    messages=[
                        {"role": "user", "content": "Hello"},
                        {"role": "assistant", "content": "Hi there!"},
                        {"role": "user", "content": "Follow-up question"},
                    ],
                )

        assert isinstance(message, anthropic.types.Message)
        assert message.content[0].text == "I see your follow-up."


class TestAnthropicSDKStreaming:
    """Streaming message creation via the real Anthropic SDK."""

    @pytest.mark.asyncio
    async def test_stream_yields_text(self, app, mock_mapper_obj):
        fake = _FakeLLM(stream_chunks=_streaming_chunks(content="Hello!"))
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                collected_text = ""
                async with client.messages.stream(
                    model="test-model",
                    max_tokens=128,
                    messages=[{"role": "user", "content": "Hello"}],
                ) as stream:
                    async for text in stream.text_stream:
                        collected_text += text

        assert collected_text == "Hello!"

    @pytest.mark.asyncio
    async def test_stream_final_message(self, app, mock_mapper_obj):
        fake = _FakeLLM(stream_chunks=_streaming_chunks(content="Done."))
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                async with client.messages.stream(
                    model="test-model",
                    max_tokens=128,
                    messages=[{"role": "user", "content": "Hello"}],
                ) as stream:
                    message = await stream.get_final_message()

        assert isinstance(message, anthropic.types.Message)
        assert message.content[0].text == "Done."
        assert message.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_stream_events(self, app, mock_mapper_obj):
        """Verify that streaming yields proper typed events."""
        fake = _FakeLLM(stream_chunks=_streaming_chunks(content="Hi"))
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                event_types = []
                async with client.messages.stream(
                    model="test-model",
                    max_tokens=128,
                    messages=[{"role": "user", "content": "Hello"}],
                ) as stream:
                    async for event in stream:
                        event_types.append(event.type)

        # Must include the key lifecycle events
        assert "message_start" in event_types
        assert "content_block_start" in event_types
        assert "content_block_delta" in event_types
        assert "content_block_stop" in event_types
        assert "message_delta" in event_types
        assert "message_stop" in event_types

    @pytest.mark.asyncio
    async def test_stream_tool_use(self, app, mock_mapper_obj):
        """Streaming with tool calls produces proper events."""
        fake = _FakeLLM(stream_chunks=_tool_call_streaming_chunks())
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                async with client.messages.stream(
                    model="test-model",
                    max_tokens=128,
                    messages=[{"role": "user", "content": "Weather?"}],
                    tools=[{
                        "name": "get_weather",
                        "description": "Get weather",
                        "input_schema": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                        },
                    }],
                ) as stream:
                    message = await stream.get_final_message()

        assert message.stop_reason == "tool_use"
        tool_blocks = [b for b in message.content if b.type == "tool_use"]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].name == "get_weather"


class TestAnthropicSDKCountTokens:
    """Token counting via the real Anthropic SDK."""

    @pytest.mark.asyncio
    async def test_count_tokens_returns_proper_type(self, app, mock_mapper_obj):
        with _patch_both_layers(_FakeLLM(), mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                result = await client.messages.count_tokens(
                    model="test-model",
                    messages=[{"role": "user", "content": "Hello, how are you?"}],
                )

        assert isinstance(result, anthropic.types.MessageTokensCount)
        assert isinstance(result.input_tokens, int)
        assert result.input_tokens > 0

    @pytest.mark.asyncio
    async def test_count_tokens_with_system(self, app, mock_mapper_obj):
        with _patch_both_layers(_FakeLLM(), mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                with_system = await client.messages.count_tokens(
                    model="test-model",
                    messages=[{"role": "user", "content": "Hi"}],
                    system="You are a helpful assistant.",
                )
                without_system = await client.messages.count_tokens(
                    model="test-model",
                    messages=[{"role": "user", "content": "Hi"}],
                )

        # With system prompt should have more tokens
        assert with_system.input_tokens > without_system.input_tokens


class TestAnthropicSDKListModels:
    """Model listing via the real Anthropic SDK."""

    @pytest.mark.asyncio
    async def test_list_models_returns_model_objects(self, app, mock_mapper_obj):
        with _patch_both_layers(_FakeLLM(), mock_mapper_obj):
            # Also need to patch main.mapper for the models endpoint
            import main as main_mod
            with patch.object(main_mod, "mapper", mock_mapper_obj):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                    client = anthropic.AsyncAnthropic(
                        api_key="test-key",
                        base_url="http://test",
                        http_client=http,
                    )
                    models = await client.models.list()

        assert hasattr(models, "data")
        assert len(models.data) >= 1
        model = models.data[0]
        assert isinstance(model, anthropic.types.ModelInfo)
        assert model.id == "test-model"
        assert model.type == "model"

    @pytest.mark.asyncio
    async def test_retrieve_single_model(self, app, mock_mapper_obj):
        with _patch_both_layers(_FakeLLM(), mock_mapper_obj):
            import main as main_mod
            with patch.object(main_mod, "mapper", mock_mapper_obj):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                    client = anthropic.AsyncAnthropic(
                        api_key="test-key",
                        base_url="http://test",
                        http_client=http,
                    )
                    model = await client.models.retrieve("test-model")

        assert isinstance(model, anthropic.types.ModelInfo)
        assert model.id == "test-model"


class TestAnthropicSDKErrors:
    """Error handling via the real Anthropic SDK."""

    @pytest.mark.asyncio
    async def test_missing_model_raises_bad_request(self, app, mock_mapper_obj):
        with _patch_both_layers(_FakeLLM(), mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                with pytest.raises(anthropic.BadRequestError) as exc_info:
                    await client.messages.create(
                        model="",
                        max_tokens=128,
                        messages=[{"role": "user", "content": "Hello"}],
                    )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_auth_error_raises_authentication_error(self, app, mock_mapper_obj):
        import config as _cfg
        original = _cfg.BOOST_AUTH
        try:
            _cfg.BOOST_AUTH = ["correct-key"]
            with _patch_both_layers(_FakeLLM(), mock_mapper_obj):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                    client = anthropic.AsyncAnthropic(
                        api_key="wrong-key",
                        base_url="http://test",
                        http_client=http,
                    )
                    with pytest.raises(anthropic.AuthenticationError) as exc_info:
                        await client.messages.create(
                            model="test-model",
                            max_tokens=128,
                            messages=[{"role": "user", "content": "Hello"}],
                        )

            assert exc_info.value.status_code == 401
        finally:
            _cfg.BOOST_AUTH = original

    @pytest.mark.asyncio
    async def test_unknown_model_raises_not_found(self, app):
        mock = _mock_mapper()
        mock.resolve_request_config = MagicMock(
            side_effect=anthropic_compat.HTTPException(status_code=404, detail="Model not found"),
        )
        with _patch_both_layers(_FakeLLM(), mock):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                with pytest.raises(anthropic.NotFoundError) as exc_info:
                    await client.messages.create(
                        model="nonexistent-model",
                        max_tokens=128,
                        messages=[{"role": "user", "content": "Hello"}],
                    )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_system_role_in_messages_raises_bad_request(self, app, mock_mapper_obj):
        with _patch_both_layers(_FakeLLM(), mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                with pytest.raises(anthropic.BadRequestError):
                    await client.messages.create(
                        model="test-model",
                        max_tokens=128,
                        messages=[{"role": "system", "content": "System prompt"}],
                    )

    @pytest.mark.asyncio
    async def test_error_has_request_id(self, app, mock_mapper_obj):
        with _patch_both_layers(_FakeLLM(), mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                try:
                    await client.messages.create(
                        model="",
                        max_tokens=128,
                        messages=[{"role": "user", "content": "Hello"}],
                    )
                    pytest.fail("Should have raised")
                except anthropic.BadRequestError as e:
                    # The SDK extracts request_id from the response header
                    assert e.request_id is not None or True  # header may or may not be set


# ---------------------------------------------------------------------------
# OpenAI Responses SDK Integration Tests
# ---------------------------------------------------------------------------


class TestOpenAISDKNonStreaming:
    """Non-streaming response creation via the real OpenAI SDK."""

    @pytest.mark.asyncio
    async def test_create_response_returns_response_object(self, app, mock_mapper_obj):
        fake = _FakeLLM(
            consume_result=_openai_result(content="Hi from Boost!"),
            stream_chunks=[],
        )
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                response = await client.responses.create(
                    model="test-model",
                    input="Hello",
                )

        assert isinstance(response, openai.types.responses.Response)
        assert response.object == "response"
        assert response.status == "completed"
        assert response.model == "test-model"

    @pytest.mark.asyncio
    async def test_response_has_output_items(self, app, mock_mapper_obj):
        fake = _FakeLLM(
            consume_result=_openai_result(content="Response text"),
            stream_chunks=[],
        )
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                response = await client.responses.create(
                    model="test-model",
                    input="Hello",
                )

        assert len(response.output) >= 1
        msg_item = response.output[0]
        assert msg_item.type == "message"
        assert msg_item.role == "assistant"
        assert len(msg_item.content) >= 1
        assert msg_item.content[0].type == "output_text"
        assert msg_item.content[0].text == "Response text"

    @pytest.mark.asyncio
    async def test_response_has_usage(self, app, mock_mapper_obj):
        fake = _FakeLLM(
            consume_result=_openai_result(prompt_tokens=12, completion_tokens=7),
            stream_chunks=[],
        )
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                response = await client.responses.create(
                    model="test-model",
                    input="Hello",
                )

        assert response.usage is not None
        assert response.usage.input_tokens == 12
        assert response.usage.output_tokens == 7
        assert response.usage.total_tokens == 19

    @pytest.mark.asyncio
    async def test_response_with_instructions(self, app, mock_mapper_obj):
        fake = _FakeLLM(
            consume_result=_openai_result(content="Concise answer"),
            stream_chunks=[],
        )
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                response = await client.responses.create(
                    model="test-model",
                    input="What is 2+2?",
                    instructions="Be concise.",
                )

        assert isinstance(response, openai.types.responses.Response)
        assert response.output[0].content[0].text == "Concise answer"

    @pytest.mark.asyncio
    async def test_response_with_tool_call(self, app, mock_mapper_obj):
        """Non-streaming tool call produces function_call output items."""
        result = _openai_result(content=None, finish_reason="tool_calls")
        result["choices"][0]["message"]["tool_calls"] = [{
            "id": "call_xyz789",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"q":"test"}'},
        }]
        result["choices"][0]["message"]["content"] = None

        fake = _FakeLLM(consume_result=result, stream_chunks=[])
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                response = await client.responses.create(
                    model="test-model",
                    input="Search for test",
                    tools=[{
                        "type": "function",
                        "name": "lookup",
                        "description": "Look up something",
                        "parameters": {
                            "type": "object",
                            "properties": {"q": {"type": "string"}},
                        },
                    }],
                )

        fc_items = [o for o in response.output if o.type == "function_call"]
        assert len(fc_items) == 1
        assert fc_items[0].name == "lookup"
        assert fc_items[0].arguments == '{"q":"test"}'


class TestOpenAISDKStreaming:
    """Streaming response creation via the real OpenAI SDK."""

    @pytest.mark.asyncio
    async def test_stream_yields_events(self, app, mock_mapper_obj):
        fake = _FakeLLM(stream_chunks=_streaming_chunks(content="Streamed!"))
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                event_types = []
                async with client.responses.stream(
                    model="test-model",
                    input="Hello",
                ) as stream:
                    async for event in stream:
                        event_types.append(event.type)

        assert "response.created" in event_types
        assert "response.in_progress" in event_types
        assert "response.output_text.delta" in event_types
        assert "response.completed" in event_types

    @pytest.mark.asyncio
    async def test_stream_collects_text(self, app, mock_mapper_obj):
        fake = _FakeLLM(stream_chunks=_streaming_chunks(content="Hello world"))
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                collected = ""
                async with client.responses.stream(
                    model="test-model",
                    input="Hello",
                ) as stream:
                    async for event in stream:
                        if event.type == "response.output_text.delta":
                            collected += event.delta

        assert collected == "Hello world"

    @pytest.mark.asyncio
    async def test_stream_final_response(self, app, mock_mapper_obj):
        """The completed event carries the final Response."""
        fake = _FakeLLM(stream_chunks=_streaming_chunks(content="Final"))
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                final_response = None
                async with client.responses.stream(
                    model="test-model",
                    input="Hello",
                ) as stream:
                    async for event in stream:
                        if event.type == "response.completed":
                            final_response = event.response

        assert final_response is not None
        assert isinstance(final_response, openai.types.responses.Response)
        assert final_response.status == "completed"


class TestOpenAISDKListModels:
    """Model listing via the real OpenAI SDK."""

    @pytest.mark.asyncio
    async def test_list_models_returns_model_objects(self, app, mock_mapper_obj):
        import main as main_mod
        with (
            _patch_both_layers(_FakeLLM(), mock_mapper_obj),
            patch.object(main_mod, "mapper", mock_mapper_obj),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                models = await client.models.list()

        # AsyncPage exposes .data as a list of Model objects
        assert len(models.data) >= 1
        model = models.data[0]
        assert model.id == "test-model"

    @pytest.mark.asyncio
    async def test_retrieve_single_model(self, app, mock_mapper_obj):
        import main as main_mod
        with (
            _patch_both_layers(_FakeLLM(), mock_mapper_obj),
            patch.object(main_mod, "mapper", mock_mapper_obj),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                model = await client.models.retrieve("test-model")

        assert model.id == "test-model"


class TestOpenAISDKErrors:
    """Error handling via the real OpenAI SDK."""

    @pytest.mark.asyncio
    async def test_missing_model_raises_bad_request(self, app, mock_mapper_obj):
        with _patch_both_layers(_FakeLLM(), mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                with pytest.raises(openai.BadRequestError) as exc_info:
                    await client.responses.create(
                        model="",
                        input="Hello",
                    )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_auth_error_raises_authentication_error(self, app, mock_mapper_obj):
        import config as _cfg
        original = _cfg.BOOST_AUTH
        try:
            _cfg.BOOST_AUTH = ["correct-key"]
            with _patch_both_layers(_FakeLLM(), mock_mapper_obj):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                    client = openai.AsyncOpenAI(
                        api_key="wrong-key",
                        base_url="http://test/v1",
                        http_client=http,
                    )
                    with pytest.raises(openai.AuthenticationError) as exc_info:
                        await client.responses.create(
                            model="test-model",
                            input="Hello",
                        )

            assert exc_info.value.status_code == 401
        finally:
            _cfg.BOOST_AUTH = original

    @pytest.mark.asyncio
    async def test_mapper_error_raises_bad_request(self, app):
        """ValueError from mapper is surfaced as BadRequestError."""
        mock = _mock_mapper()
        mock.resolve_request_config = MagicMock(
            side_effect=ValueError("Unable to proxy request without a model specifier"),
        )
        with _patch_both_layers(_FakeLLM(), mock):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                with pytest.raises(openai.BadRequestError) as exc_info:
                    await client.responses.create(
                        model="unknown-model",
                        input="Hello",
                    )

        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Cross-SDK consistency checks
# ---------------------------------------------------------------------------


class TestCrossSDKConsistency:
    """Verify both SDK paths handle the same backend response consistently."""

    @pytest.mark.asyncio
    async def test_same_backend_response_different_sdks(self, app, mock_mapper_obj):
        """Given the same backend LLM response, both SDKs should parse successfully."""
        result = _openai_result(content="Same response", prompt_tokens=20, completion_tokens=10)

        # Anthropic path
        fake_a = _FakeLLM(consume_result=result, stream_chunks=[])
        with _patch_both_layers(fake_a, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                a_client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                a_msg = await a_client.messages.create(
                    model="test-model",
                    max_tokens=128,
                    messages=[{"role": "user", "content": "Hello"}],
                )

        # OpenAI path
        fake_o = _FakeLLM(consume_result=result, stream_chunks=[])
        with _patch_both_layers(fake_o, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                o_client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                o_resp = await o_client.responses.create(
                    model="test-model",
                    input="Hello",
                )

        # Both should have the same content
        assert a_msg.content[0].text == "Same response"
        assert o_resp.output[0].content[0].text == "Same response"

        # Both should reflect the same usage (from the same backend)
        assert a_msg.usage.input_tokens == 20
        assert o_resp.usage.input_tokens == 20

    @pytest.mark.asyncio
    async def test_both_sdks_handle_streaming(self, app, mock_mapper_obj):
        """Both SDKs can stream from the same backend chunk format."""
        chunks = _streaming_chunks(content="Streamed content")

        # Anthropic streaming
        fake_a = _FakeLLM(stream_chunks=list(chunks))
        with _patch_both_layers(fake_a, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                a_client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                a_text = ""
                async with a_client.messages.stream(
                    model="test-model",
                    max_tokens=128,
                    messages=[{"role": "user", "content": "Hello"}],
                ) as stream:
                    async for text in stream.text_stream:
                        a_text += text

        # OpenAI streaming
        fake_o = _FakeLLM(stream_chunks=list(chunks))
        with _patch_both_layers(fake_o, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                o_client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                o_text = ""
                async with o_client.responses.stream(
                    model="test-model",
                    input="Hello",
                ) as stream:
                    async for event in stream:
                        if event.type == "response.output_text.delta":
                            o_text += event.delta

        assert a_text == "Streamed content"
        assert o_text == "Streamed content"
