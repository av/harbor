"""Tests for BackendError handling in streaming scenarios.

Verifies that BackendError raised by the LLM background task propagates
through the generator to the streaming converters, which catch it and
emit appropriate error messages in the SSE stream.
"""

import json
import os
import sys

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
os.chdir(SRC_DIR)

from llm import BackendError
import anthropic_compat
import responses_compat


# ---------------------------------------------------------------------------
# Anthropic streaming converter BackendError tests
# ---------------------------------------------------------------------------


class TestAnthropicStreamingBackendError:
    """BackendError raised during streaming is properly handled by the
    Anthropic stream converter."""

    @pytest.mark.asyncio
    async def test_backend_429_before_any_data(self):
        """BackendError(429) before any chunks produces valid SSE with rate limit message."""
        async def response_stream():
            if False:
                yield  # pragma: no cover
            raise BackendError(429, "rate limited", {"retry-after": "30"})

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert '"type": "message_start"' in joined
        assert '"type": "message_delta"' in joined
        assert '"type": "message_stop"' in joined
        assert "Rate limit exceeded" in joined
        assert "Stream error" in joined
        assert "rate limited" not in joined

    @pytest.mark.asyncio
    async def test_backend_500_before_any_data(self):
        """BackendError(500) before any chunks reports generic server error."""
        async def response_stream():
            if False:
                yield  # pragma: no cover
            raise BackendError(500, "internal: secret_db_password", {})

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert '"type": "message_start"' in joined
        assert '"type": "message_stop"' in joined
        assert "Backend server error" in joined
        assert "secret_db_password" not in joined

    @pytest.mark.asyncio
    async def test_backend_429_mid_stream(self):
        """BackendError(429) after some chunks still produces valid SSE."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "partial"}}]}\n\n'
            raise BackendError(429, "rate limited", {"retry-after": "10"})

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert "partial" in joined
        assert "Rate limit exceeded" in joined
        assert '"type": "message_start"' in joined
        assert '"type": "message_stop"' in joined

    @pytest.mark.asyncio
    async def test_backend_500_mid_stream(self):
        """BackendError(500) after some chunks reports server error."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": " world"}}]}\n\n'
            raise BackendError(500, "upstream crashed")

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert "Hello" in joined
        assert " world" in joined
        assert "Backend server error" in joined
        assert '"type": "message_stop"' in joined

    @pytest.mark.asyncio
    async def test_backend_error_other_status(self):
        """BackendError with non-429/5xx status reports generic failure."""
        async def response_stream():
            if False:
                yield  # pragma: no cover
            raise BackendError(403, "forbidden")

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert "Backend request failed" in joined
        assert '"type": "message_stop"' in joined

    @pytest.mark.asyncio
    async def test_backend_429_during_thinking_block(self):
        """BackendError during an open thinking block closes it before emitting error."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"reasoning_content": "Let me think..."}}]}\n\n'
            raise BackendError(429, "rate limited")

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert '"type": "thinking"' in joined
        assert "Let me think..." in joined
        assert "Rate limit exceeded" in joined
        assert '"type": "message_stop"' in joined

    @pytest.mark.asyncio
    async def test_generic_exception_still_works(self):
        """Non-BackendError exceptions still produce generic error message."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "hi"}}]}\n\n'
            raise RuntimeError("something broke internally")

        events = [
            event async for event in
            anthropic_compat._anthropic_stream_converter(response_stream(), "test-model")
        ]
        joined = "".join(events)

        assert "internal error" in joined.lower()
        assert "something broke" not in joined
        assert '"type": "message_stop"' in joined


# ---------------------------------------------------------------------------
# Responses streaming converter BackendError tests
# ---------------------------------------------------------------------------


class TestResponsesStreamingBackendError:
    """BackendError raised during streaming is properly handled by the
    Responses stream converter."""

    @pytest.mark.asyncio
    async def test_backend_429_before_any_data(self):
        """BackendError(429) before any chunks produces valid SSE with rate limit message."""
        async def response_stream():
            if False:
                yield  # pragma: no cover
            raise BackendError(429, "rate limited", {"retry-after": "30"})

        events = [
            event async for event in
            responses_compat._responses_stream_converter(
                response_stream(), "test-model", "resp_123"
            )
        ]
        joined = "".join(events)

        assert "response.created" in joined
        assert "response.failed" in joined
        assert "Rate limit exceeded" in joined
        assert "Stream error" in joined
        assert "rate limited" not in joined

    @pytest.mark.asyncio
    async def test_backend_500_before_any_data(self):
        """BackendError(500) before any chunks reports generic server error."""
        async def response_stream():
            if False:
                yield  # pragma: no cover
            raise BackendError(500, "internal: secret_db_password", {})

        events = [
            event async for event in
            responses_compat._responses_stream_converter(
                response_stream(), "test-model", "resp_123"
            )
        ]
        joined = "".join(events)

        assert "response.created" in joined
        assert "response.failed" in joined
        assert "Backend server error" in joined
        assert "secret_db_password" not in joined

    @pytest.mark.asyncio
    async def test_backend_429_mid_stream(self):
        """BackendError(429) after some chunks still produces valid SSE."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "partial"}}]}\n\n'
            raise BackendError(429, "rate limited", {"retry-after": "10"})

        events = [
            event async for event in
            responses_compat._responses_stream_converter(
                response_stream(), "test-model", "resp_123"
            )
        ]
        joined = "".join(events)

        assert "partial" in joined
        assert "Rate limit exceeded" in joined
        assert "response.failed" in joined

    @pytest.mark.asyncio
    async def test_backend_500_mid_stream(self):
        """BackendError(500) after some chunks reports server error."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
            yield 'data: {"choices": [{"delta": {"content": " world"}}]}\n\n'
            raise BackendError(500, "upstream crashed")

        events = [
            event async for event in
            responses_compat._responses_stream_converter(
                response_stream(), "test-model", "resp_123"
            )
        ]
        joined = "".join(events)

        assert "Hello" in joined
        assert " world" in joined
        assert "Backend server error" in joined
        assert "response.failed" in joined

    @pytest.mark.asyncio
    async def test_backend_error_other_status(self):
        """BackendError with non-429/5xx status reports generic failure."""
        async def response_stream():
            if False:
                yield  # pragma: no cover
            raise BackendError(403, "forbidden")

        events = [
            event async for event in
            responses_compat._responses_stream_converter(
                response_stream(), "test-model", "resp_123"
            )
        ]
        joined = "".join(events)

        assert "Backend request failed" in joined
        assert "response.failed" in joined

    @pytest.mark.asyncio
    async def test_backend_429_during_reasoning(self):
        """BackendError during an open reasoning item closes it before emitting error."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"reasoning_content": "Let me think..."}}]}\n\n'
            raise BackendError(429, "rate limited")

        events = [
            event async for event in
            responses_compat._responses_stream_converter(
                response_stream(), "test-model", "resp_123"
            )
        ]
        joined = "".join(events)

        assert "Let me think..." in joined
        assert "Rate limit exceeded" in joined
        assert "response.failed" in joined

    @pytest.mark.asyncio
    async def test_generic_exception_still_works(self):
        """Non-BackendError exceptions still produce generic error message."""
        async def response_stream():
            yield 'data: {"choices": [{"delta": {"content": "hi"}}]}\n\n'
            raise RuntimeError("something broke internally")

        events = [
            event async for event in
            responses_compat._responses_stream_converter(
                response_stream(), "test-model", "resp_123"
            )
        ]
        joined = "".join(events)

        assert "internal error" in joined.lower()
        assert "something broke" not in joined
        assert "response.failed" in joined


# ---------------------------------------------------------------------------
# Integration tests (full route handler path)
# ---------------------------------------------------------------------------


from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient


def _make_anthropic_app():
    app = FastAPI()
    app.include_router(anthropic_compat.anthropic_compatible_routes)

    @app.exception_handler(HTTPException)
    async def _handler(request: Request, exc: HTTPException):
        error_type = anthropic_compat.ERROR_TYPE_MAP.get(exc.status_code, "api_error")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": "error",
                "error": {"type": error_type, "message": str(exc.detail)},
            },
        )

    return app


def _make_responses_app():
    app = FastAPI()
    app.include_router(responses_compat.responses_compatible_routes)

    @app.exception_handler(HTTPException)
    async def _handler(request: Request, exc: HTTPException):
        error_type = responses_compat.ERROR_TYPE_MAP.get(exc.status_code, "server_error")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "message": str(exc.detail),
                    "type": error_type,
                    "param": None,
                    "code": None,
                },
            },
        )

    return app


_ANTHRO_BODY = {
    "model": "claude-test",
    "max_tokens": 128,
    "messages": [{"role": "user", "content": "Hello"}],
}


class _FakeLLM:
    def __init__(self, **kwargs):
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
            yield 'data: {"choices": [{"delta": {"content": "hi"}}]}\n\n'
        return _gen()

    async def consume_stream(self, stream):
        async for _ in stream:
            pass
        return None


class TestAnthropicStreamingBackendErrorIntegration:
    """Full route integration tests for BackendError in streaming."""

    def setup_method(self):
        import config as _cfg
        _cfg.BOOST_AUTH = []

    def test_streaming_backend_429(self):
        async def _gen():
            if False:
                yield  # pragma: no cover
            raise BackendError(429, "rate limited", {"retry-after": "30"})

        fake_llm = _FakeLLM()
        fake_llm.serve = AsyncMock(return_value=_gen())

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            app = _make_anthropic_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json={**_ANTHRO_BODY, "stream": True})

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        assert "Rate limit exceeded" in resp.text
        assert '"type": "message_stop"' in resp.text

    def test_streaming_backend_500_sanitized(self):
        async def _gen():
            yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
            raise BackendError(500, "secret internal info")

        fake_llm = _FakeLLM()
        fake_llm.serve = AsyncMock(return_value=_gen())

        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            app = _make_anthropic_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/v1/messages", json={**_ANTHRO_BODY, "stream": True})

        assert resp.status_code == 200
        assert "Hi" in resp.text
        assert "Backend server error" in resp.text
        assert "secret internal" not in resp.text


class TestResponsesStreamingBackendErrorIntegration:
    """Full route integration tests for BackendError in streaming."""

    def setup_method(self):
        import config as _cfg
        _cfg.BOOST_AUTH = []

    def test_streaming_backend_429(self):
        mock_llm = MagicMock()
        mock_llm.workflow = None
        mock_llm.boost_params = {}

        async def _serve():
            async def _gen():
                if False:
                    yield  # pragma: no cover
                raise BackendError(429, "rate limited", {"retry-after": "30"})
            return _gen()

        mock_llm.serve = _serve

        with (
            patch.object(responses_compat, "mapper") as mock_mapper,
            patch.object(responses_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=mock_llm)

            app = _make_responses_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/v1/responses", json={
                "model": "gpt-4o", "input": "hello", "stream": True,
            })

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        assert "Rate limit exceeded" in resp.text
        assert "response.failed" in resp.text

    def test_streaming_backend_500_sanitized(self):
        mock_llm = MagicMock()
        mock_llm.workflow = None
        mock_llm.boost_params = {}

        async def _serve():
            async def _gen():
                yield 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
                raise BackendError(500, "secret internal info")
            return _gen()

        mock_llm.serve = _serve

        with (
            patch.object(responses_compat, "mapper") as mock_mapper,
            patch.object(responses_compat, "llm_mod") as mock_llm_mod,
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=mock_llm)

            app = _make_responses_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/v1/responses", json={
                "model": "gpt-4o", "input": "hello", "stream": True,
            })

        assert resp.status_code == 200
        assert "Hi" in resp.text
        assert "Backend server error" in resp.text
        assert "secret internal" not in resp.text
