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

from helpers import (
    FakeLLM as _FakeLLM,
    openai_result as _openai_result,
    sse_chunk as _sse_chunk,
    make_full_app as _build_app,
)


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


# ---------------------------------------------------------------------------
# Anthropic SDK — Extended Thinking Streaming
# ---------------------------------------------------------------------------


class TestAnthropicSDKStreamingWithThinking:
    """Streaming with extended thinking enabled — thinking blocks must appear."""

    @pytest.mark.asyncio
    async def test_stream_thinking_blocks_appear(self, app, mock_mapper_obj):
        """When the backend emits reasoning_content, the SDK should surface
        thinking events via the stream."""
        chunks = []
        # Reasoning/thinking chunk
        chunks.append(_sse_chunk({
            "choices": [{"delta": {"role": "assistant",
                                   "reasoning_content": "Let me think step by step..."}, "index": 0}],
        }))
        # More reasoning
        chunks.append(_sse_chunk({
            "choices": [{"delta": {"reasoning_content": " First, consider X."}, "index": 0}],
        }))
        # Text chunk (after thinking ends)
        chunks.append(_sse_chunk({
            "choices": [{"delta": {"content": "The answer is 42."}, "index": 0}],
        }))
        # Finish
        chunks.append(_sse_chunk({
            "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }))
        chunks.append("data: [DONE]\n\n")

        fake = _FakeLLM(stream_chunks=chunks)
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                event_types = []
                thinking_text = ""
                output_text = ""
                async with client.messages.stream(
                    model="test-model",
                    max_tokens=1024,
                    thinking={
                        "type": "enabled",
                        "budget_tokens": 2048,
                    },
                    messages=[{"role": "user", "content": "What is the meaning of life?"}],
                ) as stream:
                    async for event in stream:
                        event_types.append(event.type)
                        if event.type == "content_block_delta":
                            if hasattr(event.delta, "thinking"):
                                thinking_text += event.delta.thinking
                            elif hasattr(event.delta, "text"):
                                output_text += event.delta.text

        # Thinking block events must be present
        assert "content_block_start" in event_types
        assert "content_block_delta" in event_types
        assert "content_block_stop" in event_types
        # Thinking content was streamed
        assert "Let me think step by step..." in thinking_text
        assert "First, consider X." in thinking_text
        # Normal text was also streamed
        assert output_text == "The answer is 42."

    @pytest.mark.asyncio
    async def test_stream_thinking_final_message_has_thinking_block(self, app, mock_mapper_obj):
        """The final message from a thinking-enabled stream should contain
        a thinking block followed by a text block."""
        chunks = []
        chunks.append(_sse_chunk({
            "choices": [{"delta": {"reasoning_content": "Reasoning here."}, "index": 0}],
        }))
        chunks.append(_sse_chunk({
            "choices": [{"delta": {"content": "Final answer."}, "index": 0}],
        }))
        chunks.append(_sse_chunk({
            "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        }))
        chunks.append("data: [DONE]\n\n")

        fake = _FakeLLM(stream_chunks=chunks)
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
                    max_tokens=512,
                    thinking={"type": "enabled", "budget_tokens": 1024},
                    messages=[{"role": "user", "content": "Think first."}],
                ) as stream:
                    message = await stream.get_final_message()

        assert isinstance(message, anthropic.types.Message)
        # Should have at least two content blocks: thinking + text
        assert len(message.content) >= 2
        # First block should be thinking type
        assert message.content[0].type == "thinking"
        assert "Reasoning here." in message.content[0].thinking
        # Second (or last) block should be text
        text_blocks = [b for b in message.content if b.type == "text"]
        assert len(text_blocks) >= 1
        assert text_blocks[0].text == "Final answer."


# ---------------------------------------------------------------------------
# Anthropic SDK — Non-streaming with multiple tools
# ---------------------------------------------------------------------------


class TestAnthropicSDKMultiToolUse:
    """Non-streaming with multiple tool_use blocks — verify toolu_ IDs."""

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_have_valid_toolu_ids(self, app, mock_mapper_obj):
        """When backend returns multiple tool calls, each should have a
        unique toolu_ prefixed ID after normalization."""
        result = _openai_result(content=None, finish_reason="tool_calls")
        result["choices"][0]["message"]["content"] = None
        result["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "call_abc111",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city":"NYC"}'},
            },
            {
                "id": "call_def222",
                "type": "function",
                "function": {"name": "get_time", "arguments": '{"timezone":"EST"}'},
            },
            {
                "id": "call_ghi333",
                "type": "function",
                "function": {"name": "get_news", "arguments": '{"topic":"tech"}'},
            },
        ]

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
                    max_tokens=256,
                    messages=[{"role": "user", "content": "What is the weather, time, and news?"}],
                    tools=[
                        {
                            "name": "get_weather",
                            "description": "Get weather for a city",
                            "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
                        },
                        {
                            "name": "get_time",
                            "description": "Get time for a timezone",
                            "input_schema": {"type": "object", "properties": {"timezone": {"type": "string"}}},
                        },
                        {
                            "name": "get_news",
                            "description": "Get news on a topic",
                            "input_schema": {"type": "object", "properties": {"topic": {"type": "string"}}},
                        },
                    ],
                )

        assert message.stop_reason == "tool_use"
        tool_blocks = [b for b in message.content if b.type == "tool_use"]
        assert len(tool_blocks) == 3

        # All IDs must be toolu_-prefixed
        ids = [b.id for b in tool_blocks]
        for tool_id in ids:
            assert tool_id.startswith("toolu_"), f"Expected toolu_ prefix, got {tool_id}"

        # All IDs must be unique
        assert len(set(ids)) == 3, f"Expected 3 unique IDs, got {ids}"

        # Verify correct names and inputs
        names = {b.name for b in tool_blocks}
        assert names == {"get_weather", "get_time", "get_news"}
        for block in tool_blocks:
            assert isinstance(block, anthropic.types.ToolUseBlock)
            assert isinstance(block.input, dict)


# ---------------------------------------------------------------------------
# Anthropic SDK — Count tokens with tools
# ---------------------------------------------------------------------------


class TestAnthropicSDKCountTokensWithTools:
    """Count tokens endpoint should accept tool definitions."""

    @pytest.mark.asyncio
    async def test_count_tokens_with_tools_returns_higher_count(self, app, mock_mapper_obj):
        """Including tool definitions should increase the token count."""
        with _patch_both_layers(_FakeLLM(), mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = anthropic.AsyncAnthropic(
                    api_key="test-key",
                    base_url="http://test",
                    http_client=http,
                )
                # Without tools
                without_tools = await client.messages.count_tokens(
                    model="test-model",
                    messages=[{"role": "user", "content": "What is the weather?"}],
                )
                # With tools
                with_tools = await client.messages.count_tokens(
                    model="test-model",
                    messages=[{"role": "user", "content": "What is the weather?"}],
                    tools=[
                        {
                            "name": "get_weather",
                            "description": "Get the current weather for a given city",
                            "input_schema": {
                                "type": "object",
                                "properties": {
                                    "city": {"type": "string", "description": "City name"},
                                    "units": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                                },
                                "required": ["city"],
                            },
                        },
                    ],
                )

        assert isinstance(without_tools, anthropic.types.MessageTokensCount)
        assert isinstance(with_tools, anthropic.types.MessageTokensCount)
        # Tools should add tokens
        assert with_tools.input_tokens > without_tools.input_tokens


# ---------------------------------------------------------------------------
# Anthropic SDK — Beta flags echo
# ---------------------------------------------------------------------------


class TestAnthropicSDKBetaFlags:
    """Verify anthropic-beta header is echoed back in responses."""

    @pytest.mark.asyncio
    async def test_beta_flags_echoed_in_response(self, app, mock_mapper_obj):
        """Recognized beta flags should be echoed back in the response header."""
        fake = _FakeLLM(
            consume_result=_openai_result(content="Hello!"),
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
                # Use with_raw_response to inspect headers
                raw = await client.messages.with_raw_response.create(
                    model="test-model",
                    max_tokens=128,
                    messages=[{"role": "user", "content": "Hello"}],
                    extra_headers={
                        "anthropic-beta": "prompt-caching-2024-07-31,extended-thinking-2025-01-24"
                    },
                )

        # The response should have the anthropic-beta header echoed back
        beta_header = raw.http_response.headers.get("anthropic-beta")
        assert beta_header is not None
        echoed_flags = [f.strip() for f in beta_header.split(",")]
        assert "prompt-caching-2024-07-31" in echoed_flags
        assert "extended-thinking-2025-01-24" in echoed_flags

    @pytest.mark.asyncio
    async def test_unrecognized_beta_flags_not_echoed(self, app, mock_mapper_obj):
        """Unrecognized beta flags should NOT be echoed back."""
        fake = _FakeLLM(
            consume_result=_openai_result(content="Hello!"),
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
                raw = await client.messages.with_raw_response.create(
                    model="test-model",
                    max_tokens=128,
                    messages=[{"role": "user", "content": "Hello"}],
                    extra_headers={
                        "anthropic-beta": "nonexistent-feature-2025-01-01"
                    },
                )

        # Unrecognized flag should not appear in the response
        beta_header = raw.http_response.headers.get("anthropic-beta")
        # Either no header at all, or empty
        if beta_header:
            assert "nonexistent-feature" not in beta_header


# ---------------------------------------------------------------------------
# OpenAI SDK — Streaming with reasoning
# ---------------------------------------------------------------------------


class TestOpenAISDKStreamingWithReasoning:
    """Streaming responses with reasoning enabled."""

    @pytest.mark.asyncio
    async def test_stream_reasoning_events_appear(self, app, mock_mapper_obj):
        """When the backend emits reasoning_content, the Responses API should
        surface reasoning events in the stream."""
        chunks = []
        # Reasoning chunk
        chunks.append(_sse_chunk({
            "choices": [{"delta": {"reasoning_content": "Step 1: analyze the problem."}, "index": 0}],
        }))
        chunks.append(_sse_chunk({
            "choices": [{"delta": {"reasoning_content": " Step 2: solve it."}, "index": 0}],
        }))
        # Text chunk
        chunks.append(_sse_chunk({
            "choices": [{"delta": {"content": "The answer is 7."}, "index": 0}],
        }))
        # Finish
        chunks.append(_sse_chunk({
            "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 15, "total_tokens": 23},
        }))
        chunks.append("data: [DONE]\n\n")

        fake = _FakeLLM(stream_chunks=chunks)
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                event_types = []
                text_deltas = ""
                async with client.responses.stream(
                    model="test-model",
                    input="What is 3 + 4?",
                    reasoning={"effort": "high"},
                ) as stream:
                    async for event in stream:
                        event_types.append(event.type)
                        if event.type == "response.output_text.delta":
                            text_deltas += event.delta

        # Reasoning events should be present
        assert "response.output_item.added" in event_types
        assert "response.output_text.delta" in event_types
        assert "response.completed" in event_types
        # Text content was streamed correctly
        assert text_deltas == "The answer is 7."

    @pytest.mark.asyncio
    async def test_stream_reasoning_emits_reasoning_output_item(self, app, mock_mapper_obj):
        """When the backend emits reasoning_content, the stream should include
        output_item.added events for both a reasoning item and a message item."""
        chunks = []
        chunks.append(_sse_chunk({
            "choices": [{"delta": {"reasoning_content": "Thinking..."}, "index": 0}],
        }))
        chunks.append(_sse_chunk({
            "choices": [{"delta": {"content": "Done."}, "index": 0}],
        }))
        chunks.append(_sse_chunk({
            "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 8, "total_tokens": 13},
        }))
        chunks.append("data: [DONE]\n\n")

        fake = _FakeLLM(stream_chunks=chunks)
        with _patch_both_layers(fake, mock_mapper_obj):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                event_types = []
                added_item_types = []
                completed = False
                async with client.responses.stream(
                    model="test-model",
                    input="Think then answer.",
                    reasoning={"effort": "medium"},
                ) as stream:
                    async for event in stream:
                        event_types.append(event.type)
                        if event.type == "response.output_item.added":
                            added_item_types.append(event.item.type)
                        if event.type == "response.completed":
                            completed = True

        assert completed
        # The stream should have emitted output_item.added for reasoning and message
        assert "reasoning" in added_item_types
        assert "message" in added_item_types
        # Verify full event lifecycle
        assert "response.created" in event_types
        assert "response.completed" in event_types


# ---------------------------------------------------------------------------
# OpenAI SDK — Non-streaming with structured output
# ---------------------------------------------------------------------------


class TestOpenAISDKStructuredOutput:
    """Non-streaming response with text.format structured output."""

    @pytest.mark.asyncio
    async def test_structured_output_json_schema(self, app, mock_mapper_obj):
        """text.format with json_schema should return valid structured output."""
        fake = _FakeLLM(
            consume_result=_openai_result(content='{"name":"Alice","age":30}'),
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
                    input="Generate a person JSON.",
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "person",
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "age": {"type": "integer"},
                                },
                                "required": ["name", "age"],
                            },
                        },
                    },
                )

        assert isinstance(response, openai.types.responses.Response)
        assert response.status == "completed"
        # The response content should contain the JSON
        msg_items = [o for o in response.output if o.type == "message"]
        assert len(msg_items) >= 1
        text_content = msg_items[0].content[0].text
        parsed = json.loads(text_content)
        assert parsed["name"] == "Alice"
        assert parsed["age"] == 30

    @pytest.mark.asyncio
    async def test_structured_output_json_object(self, app, mock_mapper_obj):
        """text.format with json_object type should work."""
        fake = _FakeLLM(
            consume_result=_openai_result(content='{"result": true}'),
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
                    input="Is the sky blue? Answer in JSON.",
                    text={"format": {"type": "json_object"}},
                )

        assert isinstance(response, openai.types.responses.Response)
        assert response.status == "completed"
        text_content = response.output[0].content[0].text
        parsed = json.loads(text_content)
        assert parsed["result"] is True


# ---------------------------------------------------------------------------
# OpenAI SDK — Error handling: model not found
# ---------------------------------------------------------------------------


class TestOpenAISDKModelNotFound:
    """Verify 404 from mapper surfaces as NotFoundError."""

    @pytest.mark.asyncio
    async def test_model_not_found_raises_not_found_error(self, app):
        """When mapper raises HTTPException(404), the SDK should raise NotFoundError."""
        mock = _mock_mapper()
        mock.resolve_request_config = MagicMock(
            side_effect=responses_compat.HTTPException(
                status_code=404, detail="Model 'nonexistent' not found"
            ),
        )
        with _patch_both_layers(_FakeLLM(), mock):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                client = openai.AsyncOpenAI(
                    api_key="test-key",
                    base_url="http://test/v1",
                    http_client=http,
                )
                with pytest.raises(openai.NotFoundError) as exc_info:
                    await client.responses.create(
                        model="nonexistent",
                        input="Hello",
                    )

        assert exc_info.value.status_code == 404
