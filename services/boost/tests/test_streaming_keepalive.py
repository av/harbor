"""Tests for streaming SSE keep-alive, retry, and connection headers.

Verifies that both Anthropic and Responses API streaming converters:
- Emit SSE retry intervals for reconnection
- Send keep-alive comments during long idle periods
- Include proper SSE headers (Cache-Control, Connection, X-Accel-Buffering)
- The Anthropic ping event still works as initial keep-alive
"""

import json
import time
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

import anthropic_compat
import responses_compat
from compat_utils import (
    SSE_HEADERS,
    SSE_KEEPALIVE_INTERVAL,
    SSE_RETRY_MS,
    sse_event,
    sse_event_with_retry,
    sse_keepalive_comment,
    sse_retry_line,
)
from helpers import (
    FakeLLM,
    make_anthropic_app,
    make_responses_app,
    make_client,
    openai_result,
    parse_anthropic_sse_events,
    parse_responses_sse_events,
    setup_mock_llm,
    streaming_chunks,
    ANTHROPIC_BODY,
    RESPONSES_BODY,
)


# ---------------------------------------------------------------------------
# compat_utils SSE helpers
# ---------------------------------------------------------------------------


class TestSSERetryLine:
    """Verify the SSE retry line format."""

    def test_retry_line_format(self):
        line = sse_retry_line()
        assert line == f"retry: {SSE_RETRY_MS}\n\n"

    def test_retry_line_is_valid_sse(self):
        line = sse_retry_line()
        assert line.startswith("retry:")
        assert line.endswith("\n\n")

    def test_retry_value_is_integer_milliseconds(self):
        line = sse_retry_line()
        value = line.split(": ")[1].strip()
        assert int(value) == SSE_RETRY_MS


class TestSSEEventWithRetry:
    """Verify the combined retry+event format."""

    def test_includes_retry_field(self):
        result = sse_event_with_retry("test.event", {"type": "test"})
        assert f"retry: {SSE_RETRY_MS}" in result

    def test_includes_event_type(self):
        result = sse_event_with_retry("test.event", {"type": "test"})
        assert "event: test.event" in result

    def test_includes_data(self):
        result = sse_event_with_retry("test.event", {"type": "test", "foo": "bar"})
        assert "data: " in result
        # Extract the data line and parse it
        for line in result.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[6:])
                assert data["type"] == "test"
                assert data["foo"] == "bar"
                break
        else:
            pytest.fail("No data: line found in SSE event")

    def test_is_single_sse_block(self):
        """The retry+event must be a single SSE block (ends with \\n\\n)."""
        result = sse_event_with_retry("test.event", {"type": "test"})
        assert result.endswith("\n\n")
        # Only one blank line (the block terminator)
        blocks = result.strip().split("\n\n")
        assert len(blocks) == 1

    def test_retry_comes_before_event(self):
        result = sse_event_with_retry("test.event", {"type": "test"})
        lines = result.strip().split("\n")
        assert lines[0].startswith("retry:")
        assert lines[1].startswith("event:")
        assert lines[2].startswith("data:")


class TestSSEKeepaliveComment:
    """Verify the SSE keep-alive comment format."""

    def test_keepalive_is_sse_comment(self):
        comment = sse_keepalive_comment()
        assert comment.startswith(":")

    def test_keepalive_ends_with_double_newline(self):
        comment = sse_keepalive_comment()
        assert comment.endswith("\n\n")

    def test_keepalive_contains_text(self):
        comment = sse_keepalive_comment()
        assert "keep-alive" in comment


class TestSSEHeaders:
    """Verify SSE_HEADERS dictionary values."""

    def test_cache_control(self):
        assert SSE_HEADERS["Cache-Control"] == "no-cache"

    def test_connection(self):
        assert SSE_HEADERS["Connection"] == "keep-alive"

    def test_x_accel_buffering(self):
        assert SSE_HEADERS["X-Accel-Buffering"] == "no"


# ---------------------------------------------------------------------------
# Anthropic stream converter: retry + keep-alive
# ---------------------------------------------------------------------------


class TestAnthropicStreamRetry:
    """Verify _anthropic_stream_converter emits SSE retry."""

    @pytest.mark.asyncio
    async def test_retry_is_first_emission(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]

        assert events[0].startswith("retry:")
        assert str(SSE_RETRY_MS) in events[0]

    @pytest.mark.asyncio
    async def test_retry_before_message_start(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]

        # events[0] is retry, events[1] is message_start, events[2] is ping
        assert "retry:" in events[0]
        assert "message_start" in events[1]
        assert "event: ping" in events[2]

    @pytest.mark.asyncio
    async def test_retry_present_in_empty_stream(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]

        assert any("retry:" in e for e in events)


class TestAnthropicStreamKeepalive:
    """Verify _anthropic_stream_converter emits keep-alive comments."""

    @pytest.mark.asyncio
    async def test_keepalive_emitted_after_idle_period(self):
        """When enough time passes between chunks, a keep-alive is emitted."""
        async def slow_stream():
            yield 'data: {"choices": [{"delta": {"content": "A"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": "B"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        # Simulate a long pause between processing chunk A and chunk B.
        # The monotonic calls in the converter are:
        #   1. init (last_event_time)
        #   2. chunk A: now check
        #   3. chunk A: last_event_time reset after text event
        #   4. chunk B: now check  <-- this should be >> last_event_time
        #   5. keepalive reset
        #   ... more for chunk B processing and finish chunk
        # We return 0 for calls 1-3, then a large value for call 4+.
        counter = {"n": 0}
        def fake_monotonic():
            counter["n"] += 1
            if counter["n"] <= 3:
                return 0.0
            return float(SSE_KEEPALIVE_INTERVAL + 1)

        with patch.object(anthropic_compat._time, "monotonic", side_effect=fake_monotonic):
            events = [
                event async for event in
                anthropic_compat._anthropic_stream_converter(slow_stream(), "test-model")
            ]

        keepalives = [e for e in events if ": keep-alive" in e]
        assert len(keepalives) >= 1

    @pytest.mark.asyncio
    async def test_no_keepalive_during_active_streaming(self):
        """When chunks arrive faster than the keep-alive interval, no comments are sent."""
        async def fast_stream():
            for i in range(10):
                yield f'data: {{"choices": [{{"delta": {{"content": "chunk{i}"}}}}]}}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(fast_stream(), "test-model")
        ]

        keepalives = [e for e in events if ": keep-alive" in e]
        # No keep-alive comments during fast streaming
        assert len(keepalives) == 0

    @pytest.mark.asyncio
    async def test_keepalive_is_valid_sse_comment(self):
        """Keep-alive must be an SSE comment (starts with :) that clients ignore."""
        comment = sse_keepalive_comment()
        # SSE spec: lines starting with : are comments
        assert comment.strip().startswith(":")
        # Should not be parseable as an event
        assert "event:" not in comment
        assert "data:" not in comment


# ---------------------------------------------------------------------------
# Responses stream converter: retry + keep-alive
# ---------------------------------------------------------------------------


class TestResponsesStreamRetry:
    """Verify _responses_stream_converter embeds SSE retry."""

    @pytest.mark.asyncio
    async def test_retry_in_first_event(self):
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            responses_compat._responses_stream_converter(response_stream(), "test-model", "resp_1")
        ]

        # The first event (response.created) should include retry
        first_event = events[0]
        assert f"retry: {SSE_RETRY_MS}" in first_event
        assert "event: response.created" in first_event

    @pytest.mark.asyncio
    async def test_retry_combined_with_created_event(self):
        """Retry must be in the same SSE block as response.created to avoid
        the OpenAI SDK crash on data-less ServerSentEvent."""
        async def response_stream():
            yield 'data: [DONE]\n\n'

        events = [
            event async for event in
            responses_compat._responses_stream_converter(response_stream(), "m", "resp_2")
        ]

        # First event should have all three: retry, event, data
        first = events[0]
        lines = first.strip().split("\n")
        has_retry = any(l.startswith("retry:") for l in lines)
        has_event = any(l.startswith("event:") for l in lines)
        has_data = any(l.startswith("data:") for l in lines)
        assert has_retry
        assert has_event
        assert has_data

    @pytest.mark.asyncio
    async def test_only_first_event_has_retry(self):
        """Only the response.created event should carry the retry field."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            responses_compat._responses_stream_converter(response_stream(), "m", "resp_3")
        ]

        retry_events = [e for e in events if "retry:" in e]
        assert len(retry_events) == 1
        assert "response.created" in retry_events[0]


class TestResponsesStreamKeepalive:
    """Verify _responses_stream_converter emits keep-alive comments."""

    @pytest.mark.asyncio
    async def test_keepalive_emitted_after_idle_period(self):
        async def slow_stream():
            yield 'data: {"choices": [{"delta": {"content": "A"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": "B"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        # The responses converter calls time.monotonic() at init, per-chunk
        # (check + reset), and at teardown.  Return 0 for the first 3 calls
        # (init, chunk A check, chunk A reset) then a large value for chunk B
        # to trigger the keep-alive.
        counter = {"n": 0}
        def fake_monotonic():
            counter["n"] += 1
            if counter["n"] <= 3:
                return 0.0
            return float(SSE_KEEPALIVE_INTERVAL + 1)

        with patch.object(responses_compat.time, "monotonic", side_effect=fake_monotonic):
            events = [
                event async for event in
                responses_compat._responses_stream_converter(slow_stream(), "test-model", "resp_ka")
            ]

        keepalives = [e for e in events if ": keep-alive" in e]
        assert len(keepalives) >= 1

    @pytest.mark.asyncio
    async def test_no_keepalive_during_active_streaming(self):
        async def fast_stream():
            for i in range(10):
                yield f'data: {{"choices": [{{"delta": {{"content": "chunk{i}"}}}}]}}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            responses_compat._responses_stream_converter(fast_stream(), "test-model", "resp_fast")
        ]

        keepalives = [e for e in events if ": keep-alive" in e]
        assert len(keepalives) == 0

    @pytest.mark.asyncio
    async def test_keepalive_does_not_break_event_sequence(self):
        """Keep-alive comments must not interfere with the event sequence."""
        async def slow_stream():
            yield 'data: {"choices": [{"delta": {"content": "X"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        counter = {"n": 0}
        def fake_monotonic():
            counter["n"] += 1
            if counter["n"] <= 3:
                return 0.0
            return float(SSE_KEEPALIVE_INTERVAL + 1)

        with patch.object(responses_compat.time, "monotonic", side_effect=fake_monotonic):
            events = [
                event async for event in
                responses_compat._responses_stream_converter(slow_stream(), "m", "resp_seq")
            ]

        # Parse only real events (skip keep-alive comments)
        parsed = parse_responses_sse_events(events)
        event_types = [t for t, _ in parsed]

        # Sequence must still be valid
        assert event_types[0] == "response.created"
        assert event_types[1] == "response.in_progress"
        assert event_types[-1] in ("response.completed", "response.incomplete")


# ---------------------------------------------------------------------------
# HTTP response headers for streaming endpoints
# ---------------------------------------------------------------------------


class TestAnthropicStreamHeaders:
    """Verify Anthropic streaming response includes proper SSE headers."""

    def test_streaming_response_has_sse_headers(self, monkeypatch):
        fake = FakeLLM(stream_chunks=streaming_chunks("Hi"))
        setup_mock_llm(monkeypatch, fake)

        app = make_anthropic_app()
        client = make_client(app)

        body = {**ANTHROPIC_BODY, "stream": True}
        resp = client.post("/v1/messages", json=body, headers={"x-api-key": "test"})

        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("connection") == "keep-alive"
        assert resp.headers.get("x-accel-buffering") == "no"

    def test_non_streaming_response_no_sse_headers(self, monkeypatch):
        result = openai_result("Hello!")
        fake = FakeLLM(
            stream_chunks=streaming_chunks("Hello!"),
            consume_result=result,
        )
        setup_mock_llm(monkeypatch, fake)

        app = make_anthropic_app()
        client = make_client(app)

        body = {**ANTHROPIC_BODY, "stream": False}
        resp = client.post("/v1/messages", json=body, headers={"x-api-key": "test"})

        assert resp.status_code == 200
        # Non-streaming should NOT have SSE-specific headers
        assert resp.headers.get("cache-control") != "no-cache"
        assert resp.headers.get("x-accel-buffering") is None


class TestResponsesStreamHeaders:
    """Verify Responses API streaming response includes proper SSE headers."""

    def test_streaming_response_has_sse_headers(self, monkeypatch):
        fake = FakeLLM(stream_chunks=streaming_chunks("Hi"))
        setup_mock_llm(monkeypatch, fake)

        app = make_responses_app()
        client = make_client(app)

        body = {**RESPONSES_BODY, "stream": True}
        resp = client.post("/v1/responses", json=body, headers={"Authorization": "Bearer test"})

        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("connection") == "keep-alive"
        assert resp.headers.get("x-accel-buffering") == "no"

    def test_non_streaming_response_no_sse_headers(self, monkeypatch):
        result = openai_result("Hello!")
        fake = FakeLLM(
            stream_chunks=streaming_chunks("Hello!"),
            consume_result=result,
        )
        setup_mock_llm(monkeypatch, fake)

        app = make_responses_app()
        client = make_client(app)

        body = {**RESPONSES_BODY, "stream": False}
        resp = client.post("/v1/responses", json=body, headers={"Authorization": "Bearer test"})

        assert resp.status_code == 200
        assert resp.headers.get("cache-control") != "no-cache"
        assert resp.headers.get("x-accel-buffering") is None


class TestChatCompletionsStreamHeaders:
    """Verify chat/completions streaming response includes proper SSE headers."""

    def test_streaming_response_has_sse_headers(self, monkeypatch):
        fake = FakeLLM(stream_chunks=streaming_chunks("Hi"))
        setup_mock_llm(monkeypatch, fake)

        from helpers import make_full_app, CHAT_COMPLETIONS_BODY
        app = make_full_app()
        client = make_client(app)

        body = {**CHAT_COMPLETIONS_BODY, "stream": True}
        resp = client.post("/v1/chat/completions", json=body)

        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("connection") == "keep-alive"
        assert resp.headers.get("x-accel-buffering") == "no"


# ---------------------------------------------------------------------------
# Anthropic ping as initial keep-alive
# ---------------------------------------------------------------------------


class TestAnthropicPingAsKeepalive:
    """Verify the Anthropic ping event still serves as initial keep-alive."""

    @pytest.mark.asyncio
    async def test_ping_after_retry_and_message_start(self):
        """Ordering: retry -> message_start -> ping -> content."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]

        assert events[0].startswith("retry:")
        assert "message_start" in events[1]
        assert "event: ping" in events[2]

    @pytest.mark.asyncio
    async def test_ping_is_not_keepalive_comment(self):
        """The Anthropic ping is a real SSE event (event: ping), not a comment."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "x"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "m")
        ]

        ping = events[2]
        assert ping.startswith("event: ping")
        # It's a real event, not an SSE comment
        assert not ping.startswith(":")


# ---------------------------------------------------------------------------
# End-to-end: SDK compatibility with retry + keepalive
# ---------------------------------------------------------------------------


class TestAnthropicSDKRetryCompat:
    """Verify retry field doesn't break Anthropic SDK parsing."""

    @pytest.mark.asyncio
    async def test_streaming_with_sdk_transport(self, monkeypatch):
        """The Anthropic SDK should parse all events despite the retry field."""
        try:
            import anthropic
        except ImportError:
            pytest.skip("anthropic SDK not installed")

        import httpx

        fake = FakeLLM(stream_chunks=streaming_chunks("Hello!"))
        setup_mock_llm(monkeypatch, fake)

        app = make_anthropic_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            client = anthropic.AsyncAnthropic(
                api_key="test-key",
                http_client=http,
            )

            async with client.messages.stream(
                model="test-model",
                max_tokens=100,
                messages=[{"role": "user", "content": "Hi"}],
            ) as stream:
                text = await stream.get_final_text()
                assert text == "Hello!"


class TestOpenAISDKRetryCompat:
    """Verify retry field doesn't break OpenAI SDK parsing."""

    @pytest.mark.asyncio
    async def test_streaming_with_sdk_transport(self, monkeypatch):
        """The OpenAI SDK should parse all events despite the retry field."""
        try:
            import openai
        except ImportError:
            pytest.skip("openai SDK not installed")

        import httpx

        fake = FakeLLM(stream_chunks=streaming_chunks("World!"))
        setup_mock_llm(monkeypatch, fake)

        app = make_responses_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            client = openai.AsyncOpenAI(
                api_key="test-key",
                http_client=http,
            )

            events = []
            async with client.responses.stream(
                model="test-model",
                input="Hi",
            ) as stream:
                async for event in stream:
                    events.append(event)

            # Should have received events without crashing
            assert len(events) > 0
            event_types = [e.type for e in events]
            assert "response.created" in event_types
            assert "response.completed" in event_types
