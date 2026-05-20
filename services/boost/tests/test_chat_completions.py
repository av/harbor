"""Tests for the /v1/chat/completions endpoint.

Verifies that the main Chat Completions handler in main.py still works
correctly after changes to auth.py, llm.py (BackendError, consume_stream),
and format.py.  Uses TestClient with mocked mapper/LLM to exercise:

- Non-streaming requests
- Streaming requests
- Direct task (passthrough) requests
- BackendError propagation with rate-limit headers
- Auth enforcement (401 status, case-insensitive Bearer)
- JSON parse errors
- Exception handler routing (chat completions uses default format)
"""

import json
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from starlette.testclient import TestClient

import llm as llm_mod
from llm import BackendError
import main
import config as _cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeLLM:
    """Minimal stand-in for llm.LLM."""

    def __init__(self, stream_chunks=None, consume_result=None,
                 chat_completion_result=None, serve_error=None, **kwargs):
        self._stream_chunks = stream_chunks or []
        self._consume_result = consume_result
        self._chat_completion_result = chat_completion_result
        self._serve_error = serve_error
        self.workflow = kwargs.get("workflow")
        self.boost_params = kwargs.get("params", {})
        self.module = kwargs.get("module")
        self.model = kwargs.get("model", "test-model")
        self.chat = type("Chat", (), {
            "has_substring": lambda self, s: False,
            "history": lambda self: [],
        })()

    async def serve(self):
        if self._serve_error:
            raise self._serve_error

        async def _gen():
            for chunk in self._stream_chunks:
                yield chunk
        return _gen()

    async def consume_stream(self, stream):
        async for _ in stream:
            pass
        return self._consume_result

    async def chat_completion(self):
        if self._chat_completion_result is None:
            raise BackendError(500, "no result configured")
        return self._chat_completion_result


def _openai_result(content="Hello!", finish_reason="stop",
                   prompt_tokens=10, completion_tokens=5):
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "test-model",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": finish_reason,
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _streaming_chunks(content="Hello!", finish_reason="stop",
                      prompt_tokens=10, completion_tokens=5):
    """Build stringified SSE chunks as LLM.serve() yields them."""
    chunks = []
    for char in content:
        chunks.append(
            f'data: {json.dumps({"choices": [{"delta": {"content": char}, "index": 0}]})}\n\n'
        )
    # Final chunk with finish_reason and usage
    chunks.append(
        f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": finish_reason, "index": 0}], "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens}})}\n\n'
    )
    chunks.append("data: [DONE]\n\n")
    return chunks


def _make_client(auth_key=None):
    if auth_key:
        _cfg.BOOST_AUTH = [auth_key]
    else:
        _cfg.BOOST_AUTH = []
    return TestClient(main.app, raise_server_exceptions=False)


def _chat_body(model="test-model", stream=False, **extra):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": stream,
        **extra,
    }
    return body


def _setup_mocks(monkeypatch, llm_instance, is_direct=False):
    """Patch mapper and llm modules globally."""
    monkeypatch.setattr("mapper.list_downstream", AsyncMock(return_value=[]))
    monkeypatch.setattr("mapper.resolve_request_config", MagicMock(return_value={
        "url": "http://fake:8080",
        "headers": {"Authorization": "Bearer sk-test"},
        "model": "test-model",
        "module": None,
        "workflow": None,
        "params": {},
    }))
    monkeypatch.setattr("mapper.is_direct_task", MagicMock(return_value=is_direct))
    monkeypatch.setattr(llm_mod, "LLM", lambda **kwargs: llm_instance)


# ===========================================================================
# Non-streaming requests
# ===========================================================================

class TestNonStreamingChatCompletions:
    """Non-streaming POST /v1/chat/completions."""

    def test_basic_non_streaming_response(self, monkeypatch):
        """A non-streaming request returns JSON with chat completion object."""
        result = _openai_result(content="Hi there!")
        fake = _FakeLLM(consume_result=result, stream_chunks=[])
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "chatcmpl-1"
        assert body["choices"][0]["message"]["content"] == "Hi there!"
        assert body["usage"]["prompt_tokens"] == 10

    def test_non_streaming_with_usage(self, monkeypatch):
        """Usage stats are present in the response."""
        result = _openai_result(prompt_tokens=42, completion_tokens=17)
        fake = _FakeLLM(consume_result=result, stream_chunks=[])
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 200
        usage = resp.json()["usage"]
        assert usage["prompt_tokens"] == 42
        assert usage["completion_tokens"] == 17
        assert usage["total_tokens"] == 59

    def test_non_streaming_finish_reason_stop(self, monkeypatch):
        result = _openai_result(finish_reason="stop")
        fake = _FakeLLM(consume_result=result, stream_chunks=[])
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.json()["choices"][0]["finish_reason"] == "stop"

    def test_non_streaming_finish_reason_length(self, monkeypatch):
        result = _openai_result(finish_reason="length")
        fake = _FakeLLM(consume_result=result, stream_chunks=[])
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.json()["choices"][0]["finish_reason"] == "length"

    def test_non_streaming_empty_content(self, monkeypatch):
        result = _openai_result(content="")
        fake = _FakeLLM(consume_result=result, stream_chunks=[])
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == ""

    def test_consume_stream_returns_none(self, monkeypatch):
        """When serve() returns None, we get a 500 error."""
        fake = _FakeLLM(stream_chunks=[])
        # Override serve to return None
        async def _serve_none():
            return None
        fake.serve = _serve_none
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 500
        assert "error" in resp.json()


# ===========================================================================
# Streaming requests
# ===========================================================================

class TestStreamingChatCompletions:
    """Streaming POST /v1/chat/completions."""

    def test_streaming_returns_event_stream(self, monkeypatch):
        chunks = _streaming_chunks(content="Hi")
        fake = _FakeLLM(stream_chunks=chunks)
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post(
            "/v1/chat/completions",
            json=_chat_body(stream=True),
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

    def test_streaming_contains_content_chunks(self, monkeypatch):
        chunks = _streaming_chunks(content="AB")
        fake = _FakeLLM(stream_chunks=chunks)
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post(
            "/v1/chat/completions",
            json=_chat_body(stream=True),
        )
        text = resp.text
        # Should contain the character deltas
        assert '"content": "A"' in text or '"content":"A"' in text
        assert '"content": "B"' in text or '"content":"B"' in text

    def test_streaming_ends_with_done(self, monkeypatch):
        chunks = _streaming_chunks(content="X")
        fake = _FakeLLM(stream_chunks=chunks)
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post(
            "/v1/chat/completions",
            json=_chat_body(stream=True),
        )
        assert "data: [DONE]" in resp.text

    def test_streaming_contains_finish_reason(self, monkeypatch):
        chunks = _streaming_chunks(content="X", finish_reason="stop")
        fake = _FakeLLM(stream_chunks=chunks)
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post(
            "/v1/chat/completions",
            json=_chat_body(stream=True),
        )
        # Parse SSE events
        events = []
        for line in resp.text.strip().split("\n"):
            line = line.strip()
            if line.startswith("data: ") and line != "data: [DONE]":
                events.append(json.loads(line[6:]))
        # The last non-DONE event should have finish_reason
        last = events[-1]
        assert last["choices"][0].get("finish_reason") == "stop"

    def test_streaming_empty_content(self, monkeypatch):
        """Streaming with no content characters, just finish."""
        chunks = _streaming_chunks(content="")
        fake = _FakeLLM(stream_chunks=chunks)
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post(
            "/v1/chat/completions",
            json=_chat_body(stream=True),
        )
        assert resp.status_code == 200
        assert "data: [DONE]" in resp.text


# ===========================================================================
# Direct task (passthrough)
# ===========================================================================

class TestDirectTaskChatCompletions:
    """When is_direct_task returns True, proxy.chat_completion() is used."""

    def test_direct_task_returns_json(self, monkeypatch):
        result = _openai_result(content="Direct answer")
        fake = _FakeLLM(chat_completion_result=result)
        _setup_mocks(monkeypatch, fake, is_direct=True)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "Direct answer"

    def test_direct_task_with_workflow_skips_passthrough(self, monkeypatch):
        """If proxy has a workflow set, direct task passthrough is skipped."""
        result = _openai_result(content="Boosted")
        # Set workflow so the direct task check fails
        fake = _FakeLLM(
            consume_result=result,
            stream_chunks=[],
            workflow={"name": "test"},
        )
        _setup_mocks(monkeypatch, fake, is_direct=True)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 200
        # Should go through boost path (serve + consume_stream)
        assert resp.json()["choices"][0]["message"]["content"] == "Boosted"

    def test_direct_task_with_boost_workflow_param_skips_passthrough(self, monkeypatch):
        """If boost_params has workflow, direct task passthrough is skipped."""
        result = _openai_result(content="Workflow result")
        fake = _FakeLLM(
            consume_result=result,
            stream_chunks=[],
            params={"workflow": "custom"},
        )
        _setup_mocks(monkeypatch, fake, is_direct=True)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "Workflow result"


# ===========================================================================
# BackendError handling
# ===========================================================================

class TestBackendErrorHandling:
    """BackendError from LLM is properly caught and forwarded."""

    def test_backend_error_returns_status_code(self, monkeypatch):
        fake = _FakeLLM(
            serve_error=BackendError(502, "Bad gateway from upstream"),
        )
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 502

    def test_backend_error_sanitizes_body(self, monkeypatch):
        """Error response should not leak raw backend body."""
        fake = _FakeLLM(
            serve_error=BackendError(500, "Internal secret: password=xyz"),
        )
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        body = resp.json()
        assert body["error"]["message"] == "Backend request failed"
        assert "password" not in json.dumps(body)

    def test_backend_error_forwards_rate_limit_headers(self, monkeypatch):
        fake = _FakeLLM(
            serve_error=BackendError(429, "Too many requests", {
                "retry-after": "30",
                "x-ratelimit-remaining-requests": "0",
            }),
        )
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 429
        assert resp.headers.get("retry-after") == "30"
        assert resp.headers.get("x-ratelimit-remaining-requests") == "0"

    def test_backend_error_with_no_headers(self, monkeypatch):
        fake = _FakeLLM(
            serve_error=BackendError(503, "Service unavailable"),
        )
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 503
        assert resp.json()["error"]["type"] == "server_error"

    def test_backend_error_format_is_openai_style(self, monkeypatch):
        """Chat completions errors use OpenAI error format."""
        fake = _FakeLLM(
            serve_error=BackendError(500, "fail"),
        )
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        body = resp.json()
        assert "error" in body
        assert "message" in body["error"]
        assert "type" in body["error"]


# ===========================================================================
# Auth enforcement
# ===========================================================================

class TestChatCompletionsAuth:
    """Auth enforcement on the chat completions endpoint."""

    def test_missing_auth_returns_401(self):
        client = _make_client(auth_key="sk-secret")
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 401

    def test_wrong_key_returns_401(self):
        client = _make_client(auth_key="sk-secret")
        resp = client.post(
            "/v1/chat/completions",
            json=_chat_body(),
            headers={"Authorization": "Bearer sk-wrong"},
        )
        assert resp.status_code == 401

    def test_correct_bearer_passes(self, monkeypatch):
        result = _openai_result()
        fake = _FakeLLM(consume_result=result, stream_chunks=[])
        _setup_mocks(monkeypatch, fake)

        client = _make_client(auth_key="sk-secret")
        resp = client.post(
            "/v1/chat/completions",
            json=_chat_body(),
            headers={"Authorization": "Bearer sk-secret"},
        )
        assert resp.status_code == 200

    def test_case_insensitive_bearer(self, monkeypatch):
        """Bearer prefix is case-insensitive (e.g. 'BEARER', 'bearer')."""
        result = _openai_result()
        fake = _FakeLLM(consume_result=result, stream_chunks=[])
        _setup_mocks(monkeypatch, fake)

        client = _make_client(auth_key="sk-secret")
        resp = client.post(
            "/v1/chat/completions",
            json=_chat_body(),
            headers={"Authorization": "BEARER sk-secret"},
        )
        assert resp.status_code == 200

    def test_x_api_key_also_works(self, monkeypatch):
        """x-api-key header is accepted (Anthropic-style auth)."""
        result = _openai_result()
        fake = _FakeLLM(consume_result=result, stream_chunks=[])
        _setup_mocks(monkeypatch, fake)

        client = _make_client(auth_key="sk-secret")
        resp = client.post(
            "/v1/chat/completions",
            json=_chat_body(),
            headers={"x-api-key": "sk-secret"},
        )
        assert resp.status_code == 200

    def test_no_auth_configured_allows_all(self, monkeypatch):
        result = _openai_result()
        fake = _FakeLLM(consume_result=result, stream_chunks=[])
        _setup_mocks(monkeypatch, fake)

        client = _make_client(auth_key=None)
        resp = client.post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 200

    def test_auth_error_uses_default_format_not_anthropic(self):
        """Auth errors on /v1/chat/completions should use default format,
        not Anthropic format (which is reserved for /v1/messages)."""
        client = _make_client(auth_key="sk-secret")
        resp = client.post("/v1/chat/completions", json=_chat_body())
        body = resp.json()
        # Should NOT have Anthropic error envelope
        assert body.get("type") != "error"
        # Should have standard FastAPI detail format
        assert "detail" in body


# ===========================================================================
# Request validation
# ===========================================================================

class TestChatCompletionsValidation:
    """Request body validation."""

    def test_invalid_json_returns_400(self):
        client = _make_client()
        resp = client.post(
            "/v1/chat/completions",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    def test_empty_body_returns_400(self):
        client = _make_client()
        resp = client.post(
            "/v1/chat/completions",
            content=b"",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    def test_stream_defaults_to_false(self, monkeypatch):
        """When stream is not specified, defaults to non-streaming (JSON)."""
        result = _openai_result()
        fake = _FakeLLM(consume_result=result, stream_chunks=[])
        _setup_mocks(monkeypatch, fake)

        client = _make_client()
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        # Non-streaming returns JSON, not text/event-stream
        assert "application/json" in resp.headers.get("content-type", "")


# ===========================================================================
# Exception handler routing
# ===========================================================================

class TestExceptionHandlerRouting:
    """The global HTTPException handler routes errors correctly for
    /v1/chat/completions (uses default format, not Anthropic/Responses)."""

    def test_exception_handler_uses_default_format(self):
        """HTTPExceptions on /v1/chat/completions get {"detail": "..."} format."""
        client = _make_client(auth_key="sk-secret")
        resp = client.post("/v1/chat/completions", json=_chat_body())
        body = resp.json()
        # Should be default FastAPI format
        assert "detail" in body
        # Should NOT be Anthropic format
        assert "type" not in body or body.get("type") != "error"
        # Should NOT be OpenAI format (no error.type/error.param)
        assert "error" not in body or "param" not in body.get("error", {})

    def test_5xx_sanitizes_error_detail(self, monkeypatch):
        """5xx errors should not leak internal information."""
        from fastapi import HTTPException

        # Make mapper raise an internal error
        monkeypatch.setattr(
            "mapper.list_downstream",
            AsyncMock(side_effect=HTTPException(status_code=500, detail="Secret internal error")),
        )

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        body = resp.json()
        # The handler should sanitize 5xx errors
        assert "Secret" not in json.dumps(body)


# ===========================================================================
# Integration: mapper.resolve_request_config called correctly
# ===========================================================================

class TestMapperIntegration:
    """Verify that the chat completions handler calls mapper correctly."""

    def test_mapper_receives_request_body(self, monkeypatch):
        """mapper.resolve_request_config is called with the decoded JSON body."""
        captured = {}

        def capture_config(body):
            captured["body"] = body
            return {
                "url": "http://fake:8080",
                "headers": {},
                "model": "test-model",
                "module": None,
                "workflow": None,
                "params": {},
            }

        result = _openai_result()
        fake = _FakeLLM(consume_result=result, stream_chunks=[])

        monkeypatch.setattr("mapper.list_downstream", AsyncMock(return_value=[]))
        monkeypatch.setattr("mapper.resolve_request_config", capture_config)
        monkeypatch.setattr("mapper.is_direct_task", MagicMock(return_value=False))
        monkeypatch.setattr(llm_mod, "LLM", lambda **kwargs: fake)

        client = _make_client()
        client.post("/v1/chat/completions", json=_chat_body(model="my-model"))

        assert captured["body"]["model"] == "my-model"
        assert captured["body"]["messages"][0]["content"] == "Hello"

    def test_mapper_value_error_propagates(self, monkeypatch):
        """ValueError from mapper (missing model) should produce an error response."""
        monkeypatch.setattr("mapper.list_downstream", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            "mapper.resolve_request_config",
            MagicMock(side_effect=ValueError("Unable to proxy request without a model specifier")),
        )

        client = _make_client()
        resp = client.post("/v1/chat/completions", json=_chat_body())
        # Should not crash (500) - the error is caught
        assert resp.status_code == 500  # unhandled ValueError becomes 500 in FastAPI
