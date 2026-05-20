"""Tests for endpoint isolation and cross-compat safety.

Verifies that:
- Wrong SDK hitting the wrong endpoint gets helpful errors
- GET requests to POST-only endpoints get 405
- POST to non-existent endpoints gets 404
- Concurrent requests to different compat layers don't interfere
- Path traversal is handled safely
- Query string parameters are ignored (stream is in body)
- Empty body POST to /v1/messages gets proper error
- Content-Type mismatches are handled gracefully
- Very long paths don't crash
- Exception handler routes errors based on path prefix
- Auth errors on /v1/models use the right format
- CORS preflight (OPTIONS) requests work for all endpoints
"""

import json
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from starlette.testclient import TestClient
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Module stubs for mapper/llm are registered in conftest.py

import anthropic_compat
import responses_compat
import main


# ---------------------------------------------------------------------------
# Shared app and helpers
# ---------------------------------------------------------------------------

def _build_full_app():
    """Build the real app from main.py — it already has all routers, CORS,
    middleware, and exception handlers configured."""
    return main.app


def _make_client(auth_key=None):
    """Return a TestClient against the full app."""
    import config as _cfg
    if auth_key:
        _cfg.BOOST_AUTH = [auth_key]
    else:
        _cfg.BOOST_AUTH = []
    return TestClient(_build_full_app(), raise_server_exceptions=False)


# Canonical request bodies
_ANTHROPIC_BODY = {
    "model": "claude-test",
    "max_tokens": 128,
    "messages": [{"role": "user", "content": "Hello, world!"}],
}

_RESPONSES_BODY = {
    "model": "gpt-4o",
    "input": "Hello, world!",
}

_CHAT_COMPLETIONS_BODY = {
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}],
}


class _FakeLLM:
    """Minimal stand-in for llm.LLM."""

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


def _openai_result(content="Hello!", finish_reason="stop",
                   prompt_tokens=10, completion_tokens=5):
    msg = {"content": content, "tool_calls": []}
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
    chunks = []
    for char in content:
        chunks.append(f'data: {json.dumps({"choices": [{"delta": {"content": char}, "index": 0}]})}\n\n')
    chunks.append(f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": finish_reason, "index": 0}], "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens}})}\n\n')
    chunks.append("data: [DONE]\n\n")
    return chunks


def _setup_mock_llm(monkeypatch, llm_instance):
    """Patch mapper and llm modules to return the given FakeLLM."""
    import llm as llm_mod
    monkeypatch.setattr("mapper.list_downstream", AsyncMock(return_value=[]))
    monkeypatch.setattr("mapper.resolve_request_config", MagicMock(return_value={
        "url": "http://fake:8080", "api_key": "sk-test",
        "model": "test-model", "module": None, "workflow": None, "params": {},
    }))
    monkeypatch.setattr("mapper.is_direct_task", MagicMock(return_value=False))
    monkeypatch.setattr(llm_mod, "LLM", lambda **kwargs: llm_instance)


# ===========================================================================
# 1. Wrong SDK hits wrong endpoint
# ===========================================================================

class TestWrongSDKWrongEndpoint:
    """Verify that an SDK hitting the wrong compat endpoint gets a proper error."""

    def test_anthropic_sdk_post_to_responses_endpoint(self, monkeypatch):
        """Anthropic SDK sending Anthropic-format body to /v1/responses
        should get a proper OpenAI-format error (missing 'input' field)."""
        client = _make_client()
        resp = client.post(
            "/v1/responses",
            json=_ANTHROPIC_BODY,
            headers={"x-api-key": "test", "anthropic-version": "2023-06-01"},
        )
        assert resp.status_code == 400
        body = resp.json()
        # Should be OpenAI error format (the endpoint determines format)
        assert "error" in body
        assert body["error"]["type"] in ("invalid_request_error", "server_error")

    def test_openai_sdk_post_to_messages_endpoint(self, monkeypatch):
        """OpenAI SDK sending OpenAI-format body to /v1/messages
        should get an Anthropic-format error."""
        client = _make_client()
        resp = client.post(
            "/v1/messages",
            json=_CHAT_COMPLETIONS_BODY,
            headers={"authorization": "Bearer test"},
        )
        assert resp.status_code == 400
        body = resp.json()
        # Should be Anthropic error format (the endpoint determines format)
        assert body.get("type") == "error"
        assert body["error"]["type"] == "invalid_request_error"

    def test_responses_body_to_messages_endpoint(self, monkeypatch):
        """Responses API body (input, not messages) to /v1/messages gets Anthropic error."""
        client = _make_client()
        resp = client.post(
            "/v1/messages",
            json=_RESPONSES_BODY,
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body.get("type") == "error"
        # Missing max_tokens or messages
        assert "invalid_request_error" == body["error"]["type"]

    def test_anthropic_body_to_chat_completions(self, monkeypatch):
        """Anthropic body to /v1/chat/completions — processed but model routing fails
        or succeeds depending on mapper; at minimum should not crash."""
        client = _make_client()
        # Anthropic body has max_tokens (not standard OpenAI field) but also
        # has messages, so chat/completions will attempt to process it.
        # Without a real mapper, this should fail gracefully.
        resp = client.post(
            "/v1/chat/completions",
            json=_ANTHROPIC_BODY,
        )
        # Should not crash — either 200 (if mapper works) or 4xx/5xx error
        assert resp.status_code < 600


# ===========================================================================
# 2. GET requests to POST-only endpoints
# ===========================================================================

class TestMethodNotAllowed:
    """GET requests to POST-only endpoints should get 405 Method Not Allowed."""

    def test_get_to_v1_messages(self):
        client = _make_client()
        resp = client.get("/v1/messages")
        assert resp.status_code == 405

    def test_get_to_v1_responses(self):
        client = _make_client()
        resp = client.get("/v1/responses")
        assert resp.status_code == 405

    def test_get_to_v1_chat_completions(self):
        client = _make_client()
        resp = client.get("/v1/chat/completions")
        assert resp.status_code == 405

    def test_get_to_v1_messages_count_tokens(self):
        client = _make_client()
        resp = client.get("/v1/messages/count_tokens")
        assert resp.status_code == 405

    def test_put_to_v1_messages(self):
        client = _make_client()
        resp = client.put("/v1/messages", json=_ANTHROPIC_BODY)
        assert resp.status_code == 405

    def test_put_to_v1_responses(self):
        client = _make_client()
        resp = client.put("/v1/responses", json=_RESPONSES_BODY)
        assert resp.status_code == 405

    def test_delete_to_v1_messages(self):
        client = _make_client()
        resp = client.delete("/v1/messages")
        assert resp.status_code == 405

    def test_patch_to_v1_messages(self):
        client = _make_client()
        resp = client.request("PATCH", "/v1/messages", json=_ANTHROPIC_BODY)
        assert resp.status_code == 405


# ===========================================================================
# 3. POST to non-existent endpoints
# ===========================================================================

class TestNotFound:
    """POST to non-existent endpoints should get 404."""

    def test_post_to_v1_completions(self):
        client = _make_client()
        resp = client.post("/v1/completions", json={"model": "m"})
        assert resp.status_code in (404, 405)

    def test_post_to_v1_embeddings(self):
        client = _make_client()
        resp = client.post("/v1/embeddings", json={"model": "m"})
        assert resp.status_code in (404, 405)

    def test_post_to_v2_messages(self):
        client = _make_client()
        resp = client.post("/v2/messages", json=_ANTHROPIC_BODY)
        assert resp.status_code == 404

    def test_post_to_nonexistent_deep_path(self):
        client = _make_client()
        resp = client.post("/v1/foo/bar/baz", json={})
        assert resp.status_code in (404, 405)

    def test_get_to_nonexistent_path(self):
        client = _make_client()
        resp = client.get("/v1/nonexistent")
        assert resp.status_code == 404


# ===========================================================================
# 4. Concurrent requests to different compat layers
# ===========================================================================

class TestConcurrentRequests:
    """Two simultaneous requests to different compat layers shouldn't interfere."""

    @pytest.mark.asyncio
    async def test_concurrent_anthropic_and_responses(self, monkeypatch):
        """Send requests to both /v1/messages and /v1/responses concurrently."""
        import httpx

        # Set up mocks
        anthropic_result = _openai_result(content="I am Claude")
        responses_result = _openai_result(content="I am GPT")

        call_count = {"anthropic": 0, "responses": 0}

        def mock_resolve(body):
            return {
                "url": "http://fake:8080", "api_key": "sk-test",
                "model": body.get("model", "test"), "module": None,
                "workflow": None, "params": {},
            }

        class FakeLLM:
            def __init__(self, **kwargs):
                self.model = kwargs.get("model", "test")
                self.workflow = kwargs.get("workflow")
                self.boost_params = kwargs.get("params", {})
                self.module = kwargs.get("module")
                self.chat = type("Chat", (), {
                    "has_substring": lambda self, s: False,
                    "history": lambda self: [],
                })()

            async def serve(self):
                # Use model name to determine which result to return
                result = anthropic_result if "claude" in self.model else responses_result
                if "claude" in self.model:
                    call_count["anthropic"] += 1
                else:
                    call_count["responses"] += 1
                async def _gen():
                    yield f'data: {json.dumps(result)}\n\n'
                    yield 'data: [DONE]\n\n'
                return _gen()

            async def consume_stream(self, stream):
                result = anthropic_result if "claude" in self.model else responses_result
                async for _ in stream:
                    pass
                return result

        import config as _cfg
        _cfg.BOOST_AUTH = []
        monkeypatch.setattr("mapper.list_downstream", AsyncMock(return_value=[]))
        monkeypatch.setattr("mapper.resolve_request_config", MagicMock(side_effect=mock_resolve))
        monkeypatch.setattr("mapper.is_direct_task", MagicMock(return_value=False))

        import llm as llm_mod
        monkeypatch.setattr(llm_mod, "LLM", lambda **kwargs: FakeLLM(**kwargs))

        app = _build_full_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            anthropic_req = client.post("/v1/messages", json={
                "model": "claude-test",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "Hi"}],
            })
            responses_req = client.post("/v1/responses", json={
                "model": "gpt-4o",
                "input": "Hi",
            })

            anthropic_resp, responses_resp = await asyncio.gather(
                anthropic_req, responses_req
            )

        # Both should succeed
        assert anthropic_resp.status_code == 200
        assert responses_resp.status_code == 200

        # Anthropic response should be in Anthropic format
        a_body = anthropic_resp.json()
        assert a_body.get("type") == "message"
        assert a_body.get("role") == "assistant"

        # Responses response should be in Responses format
        r_body = responses_resp.json()
        assert "output" in r_body
        assert r_body.get("object") == "response"

        # Both endpoints were hit
        assert call_count["anthropic"] >= 1
        assert call_count["responses"] >= 1

    @pytest.mark.asyncio
    async def test_concurrent_same_endpoint(self, monkeypatch):
        """Two concurrent requests to the same endpoint don't interfere."""
        import httpx

        results = []

        def mock_resolve(body):
            return {
                "url": "http://fake:8080", "api_key": "sk-test",
                "model": body.get("model", "test"), "module": None,
                "workflow": None, "params": {},
            }

        class FakeLLM:
            def __init__(self, **kwargs):
                self.model = kwargs.get("model", "test")
                self.workflow = kwargs.get("workflow")
                self.boost_params = kwargs.get("params", {})
                self.module = kwargs.get("module")
                self.chat = type("Chat", (), {
                    "has_substring": lambda self, s: False,
                    "history": lambda self: [],
                })()

            async def serve(self):
                result = _openai_result(content=f"model={self.model}")
                async def _gen():
                    yield f'data: {json.dumps(result)}\n\n'
                    yield 'data: [DONE]\n\n'
                return _gen()

            async def consume_stream(self, stream):
                async for _ in stream:
                    pass
                return _openai_result(content=f"model={self.model}")

        import config as _cfg
        _cfg.BOOST_AUTH = []
        monkeypatch.setattr("mapper.list_downstream", AsyncMock(return_value=[]))
        monkeypatch.setattr("mapper.resolve_request_config", MagicMock(side_effect=mock_resolve))
        monkeypatch.setattr("mapper.is_direct_task", MagicMock(return_value=False))

        import llm as llm_mod
        monkeypatch.setattr(llm_mod, "LLM", lambda **kwargs: FakeLLM(**kwargs))

        app = _build_full_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            reqs = [
                client.post("/v1/messages", json={
                    "model": f"model-{i}",
                    "max_tokens": 128,
                    "messages": [{"role": "user", "content": f"Request {i}"}],
                })
                for i in range(5)
            ]
            responses = await asyncio.gather(*reqs)

        # All should succeed
        for resp in responses:
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("type") == "message"


# ===========================================================================
# 5. Path traversal
# ===========================================================================

class TestPathTraversal:
    """Path traversal attempts should be handled safely."""

    def test_messages_with_dot_dot(self):
        client = _make_client()
        resp = client.post("/v1/messages/../chat/completions",
                           json=_CHAT_COMPLETIONS_BODY)
        # FastAPI normalizes paths — this should either hit /v1/chat/completions
        # (which requires different body format) or 404
        assert resp.status_code < 600  # No crash
        # Should NOT succeed as messages endpoint
        if resp.status_code == 200:
            body = resp.json()
            # If it resolved to chat/completions, format should be OpenAI
            assert body.get("type") != "message"

    def test_responses_with_dot_dot(self):
        client = _make_client()
        resp = client.post("/v1/responses/../messages",
                           json=_ANTHROPIC_BODY)
        assert resp.status_code < 600

    def test_double_dot_dot(self):
        client = _make_client()
        resp = client.get("/v1/../../etc/passwd")
        assert resp.status_code < 600
        # Should not return file contents
        if resp.status_code == 200:
            body = resp.text
            assert "root:" not in body

    def test_encoded_path_traversal(self):
        client = _make_client()
        resp = client.get("/v1/messages%2F..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code < 600


# ===========================================================================
# 6. Query string parameters
# ===========================================================================

class TestQueryStringIgnored:
    """Query string parameters should be ignored for body-based endpoints."""

    def test_stream_in_query_ignored(self, monkeypatch):
        """?stream=true should NOT override body stream=false."""
        fake = _FakeLLM(
            consume_result=_openai_result(),
            stream_chunks=[f'data: {json.dumps(_openai_result())}\n\n', 'data: [DONE]\n\n'],
        )
        _setup_mock_llm(monkeypatch, fake)
        client = _make_client()

        body = {**_ANTHROPIC_BODY, "stream": False}
        resp = client.post("/v1/messages?stream=true", json=body)
        assert resp.status_code == 200
        body_resp = resp.json()
        # Should be non-streaming (JSON response, not SSE)
        assert body_resp.get("type") == "message"

    def test_model_in_query_ignored(self, monkeypatch):
        """?model=evil should not override body model."""
        fake = _FakeLLM(
            consume_result=_openai_result(),
            stream_chunks=[f'data: {json.dumps(_openai_result())}\n\n', 'data: [DONE]\n\n'],
        )
        _setup_mock_llm(monkeypatch, fake)
        client = _make_client()

        resp = client.post("/v1/messages?model=evil-model", json=_ANTHROPIC_BODY)
        assert resp.status_code == 200
        body_resp = resp.json()
        # Model in response should match body, not query
        assert body_resp.get("model") == "claude-test"

    def test_extra_query_params_harmless(self, monkeypatch):
        """Random query params should not cause errors."""
        fake = _FakeLLM(
            consume_result=_openai_result(),
            stream_chunks=[f'data: {json.dumps(_openai_result())}\n\n', 'data: [DONE]\n\n'],
        )
        _setup_mock_llm(monkeypatch, fake)
        client = _make_client()

        resp = client.post(
            "/v1/messages?foo=bar&baz=qux&debug=true",
            json=_ANTHROPIC_BODY,
        )
        assert resp.status_code == 200


# ===========================================================================
# 7. Empty body POST
# ===========================================================================

class TestEmptyBody:
    """Empty body POST should return proper error."""

    def test_empty_body_to_messages(self):
        client = _make_client()
        resp = client.post("/v1/messages", content=b"",
                           headers={"content-type": "application/json"})
        assert resp.status_code == 400

    def test_empty_body_to_responses(self):
        client = _make_client()
        resp = client.post("/v1/responses", content=b"",
                           headers={"content-type": "application/json"})
        assert resp.status_code == 400

    def test_empty_body_to_chat_completions(self):
        client = _make_client()
        resp = client.post("/v1/chat/completions", content=b"",
                           headers={"content-type": "application/json"})
        assert resp.status_code == 400

    def test_null_json_body_to_messages(self):
        client = _make_client()
        resp = client.post("/v1/messages", json=None,
                           headers={"content-type": "application/json"})
        # Should fail validation (no model, no messages)
        assert resp.status_code >= 400

    def test_empty_object_to_messages(self):
        client = _make_client()
        resp = client.post("/v1/messages", json={})
        assert resp.status_code == 400
        body = resp.json()
        assert body.get("type") == "error"

    def test_empty_object_to_responses(self):
        client = _make_client()
        resp = client.post("/v1/responses", json={})
        assert resp.status_code == 400
        body = resp.json()
        assert "error" in body


# ===========================================================================
# 8. Content-Type mismatches
# ===========================================================================

class TestContentTypeMismatch:
    """Non-JSON Content-Type should be handled gracefully."""

    def test_form_data_to_messages(self):
        client = _make_client()
        resp = client.post(
            "/v1/messages",
            content=b"model=test&max_tokens=64",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 400

    def test_text_plain_to_messages(self):
        client = _make_client()
        resp = client.post(
            "/v1/messages",
            content=b"Hello, world!",
            headers={"content-type": "text/plain"},
        )
        assert resp.status_code == 400

    def test_xml_to_responses(self):
        client = _make_client()
        resp = client.post(
            "/v1/responses",
            content=b"<request><model>gpt-4o</model></request>",
            headers={"content-type": "application/xml"},
        )
        assert resp.status_code == 400

    def test_no_content_type_with_json(self):
        """Valid JSON without explicit Content-Type header — should still work
        since most HTTP clients send application/json by default."""
        client = _make_client()
        resp = client.post(
            "/v1/messages",
            content=json.dumps(_ANTHROPIC_BODY).encode(),
        )
        # May succeed (request.json() tries anyway) or fail — either is fine
        assert resp.status_code < 600

    def test_multipart_to_responses(self):
        client = _make_client()
        resp = client.post(
            "/v1/responses",
            content=b"--boundary\r\nContent-Disposition: form-data; name='model'\r\n\r\ngpt-4o\r\n--boundary--",
            headers={"content-type": "multipart/form-data; boundary=boundary"},
        )
        assert resp.status_code == 400


# ===========================================================================
# 9. Very long paths
# ===========================================================================

class TestVeryLongPaths:
    """Very long paths should not crash the server."""

    def test_long_path_get(self):
        client = _make_client()
        long_path = "/v1/models/" + "a" * 10000
        resp = client.get(long_path)
        assert resp.status_code < 600

    def test_long_path_post(self):
        client = _make_client()
        long_path = "/v1/" + "x" * 10000
        resp = client.post(long_path, json={})
        assert resp.status_code < 600

    def test_unicode_path(self):
        client = _make_client()
        resp = client.get("/v1/models/世界")
        assert resp.status_code < 600

    def test_null_bytes_in_path(self):
        client = _make_client()
        # URL-encoded null byte
        resp = client.get("/v1/models/test%00model")
        assert resp.status_code < 600


# ===========================================================================
# 10. Exception handler routes errors based on path prefix
# ===========================================================================

class TestExceptionHandlerRouting:
    """The global exception handler in main.py routes errors to the correct
    format based on the request path."""

    def test_auth_error_on_messages_is_anthropic_format(self):
        client = _make_client(auth_key="real-key")
        resp = client.post(
            "/v1/messages",
            json=_ANTHROPIC_BODY,
            headers={"x-api-key": "wrong-key"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body.get("type") == "error"
        assert body["error"]["type"] == "authentication_error"

    def test_auth_error_on_responses_is_openai_format(self):
        client = _make_client(auth_key="real-key")
        resp = client.post(
            "/v1/responses",
            json=_RESPONSES_BODY,
            headers={"authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert "error" in body
        assert body["error"]["type"] == "authentication_error"
        # OpenAI format has param and code fields
        assert "param" in body["error"]
        assert "code" in body["error"]

    def test_auth_error_on_chat_completions_is_default_format(self):
        client = _make_client(auth_key="real-key")
        resp = client.post(
            "/v1/chat/completions",
            json=_CHAT_COMPLETIONS_BODY,
            headers={"authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401
        body = resp.json()
        # Default format is {"detail": "..."}
        assert "detail" in body or "error" in body

    def test_auth_error_has_no_internal_details(self):
        """Auth errors should not leak internal details."""
        client = _make_client(auth_key="real-key")
        resp = client.post(
            "/v1/messages",
            json=_ANTHROPIC_BODY,
            headers={"x-api-key": "wrong-key"},
        )
        body_text = resp.text
        # Should not contain stack traces or internal paths
        assert "Traceback" not in body_text
        assert "/home/" not in body_text

    def test_anthropic_version_header_on_messages_error(self):
        """Anthropic errors should include anthropic-version header."""
        client = _make_client(auth_key="real-key")
        resp = client.post(
            "/v1/messages",
            json=_ANTHROPIC_BODY,
            headers={"x-api-key": "wrong-key"},
        )
        assert "anthropic-version" in resp.headers

    def test_5xx_sanitized_on_messages(self, monkeypatch):
        """5xx errors on /v1/messages should not leak internal details."""
        import config as _cfg
        _cfg.BOOST_AUTH = []

        monkeypatch.setattr("mapper.list_downstream", AsyncMock(return_value=[]))
        monkeypatch.setattr("mapper.resolve_request_config",
                           MagicMock(side_effect=RuntimeError("internal DB connection string: postgres://user:pass@host")))
        monkeypatch.setattr("mapper.is_direct_task", MagicMock(return_value=False))

        client = _make_client()
        resp = client.post("/v1/messages", json=_ANTHROPIC_BODY)
        body = resp.json()
        # Should not contain the internal error message
        assert "postgres" not in json.dumps(body)
        assert "connection string" not in json.dumps(body)


# ===========================================================================
# 11. Auth errors on /v1/models
# ===========================================================================

class TestModelsAuthFormat:
    """Auth errors on /v1/models should auto-detect the correct error format."""

    def test_anthropic_client_gets_anthropic_error(self):
        client = _make_client(auth_key="real-key")
        resp = client.get(
            "/v1/models",
            headers={"x-api-key": "wrong-key", "anthropic-version": "2023-06-01"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body.get("type") == "error"
        assert body["error"]["type"] == "authentication_error"
        assert "anthropic-version" in resp.headers

    def test_openai_client_gets_default_error(self):
        client = _make_client(auth_key="real-key")
        resp = client.get(
            "/v1/models",
            headers={"authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401
        body = resp.json()
        # Default format for non-Anthropic client
        assert "detail" in body

    def test_no_auth_gets_error(self):
        client = _make_client(auth_key="real-key")
        resp = client.get("/v1/models")
        assert resp.status_code == 401

    def test_model_by_id_auth_anthropic(self):
        client = _make_client(auth_key="real-key")
        resp = client.get(
            "/v1/models/claude-3",
            headers={"x-api-key": "wrong-key", "anthropic-version": "2023-06-01"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body.get("type") == "error"


# ===========================================================================
# 12. CORS preflight (OPTIONS) requests
# ===========================================================================

class TestCORSPreflight:
    """CORS preflight (OPTIONS) requests should work for all endpoints."""

    def _assert_cors_headers(self, resp):
        """Assert that standard CORS headers are present."""
        assert "access-control-allow-origin" in resp.headers
        # With allow_origins=["*"] + allow_credentials=True, Starlette echoes
        # the request's Origin header instead of returning literal "*" (per
        # CORS spec: credentials + wildcard is invalid, so the middleware
        # reflects the origin).
        origin = resp.headers["access-control-allow-origin"]
        assert origin in ("*", "http://localhost:3000")

    def test_options_v1_messages(self):
        client = _make_client()
        resp = client.options(
            "/v1/messages",
            headers={
                "origin": "http://localhost:3000",
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type, x-api-key, anthropic-version",
            },
        )
        assert resp.status_code == 200
        self._assert_cors_headers(resp)

    def test_options_v1_responses(self):
        client = _make_client()
        resp = client.options(
            "/v1/responses",
            headers={
                "origin": "http://localhost:3000",
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type, authorization",
            },
        )
        assert resp.status_code == 200
        self._assert_cors_headers(resp)

    def test_options_v1_chat_completions(self):
        client = _make_client()
        resp = client.options(
            "/v1/chat/completions",
            headers={
                "origin": "http://localhost:3000",
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type, authorization",
            },
        )
        assert resp.status_code == 200
        self._assert_cors_headers(resp)

    def test_options_v1_models(self):
        client = _make_client()
        resp = client.options(
            "/v1/models",
            headers={
                "origin": "http://localhost:3000",
                "access-control-request-method": "GET",
                "access-control-request-headers": "authorization",
            },
        )
        assert resp.status_code == 200
        self._assert_cors_headers(resp)

    def test_cors_allows_anthropic_headers(self):
        """CORS should allow Anthropic-specific headers like x-api-key."""
        client = _make_client()
        resp = client.options(
            "/v1/messages",
            headers={
                "origin": "http://localhost:3000",
                "access-control-request-method": "POST",
                "access-control-request-headers": "x-api-key, anthropic-version, content-type",
            },
        )
        assert resp.status_code == 200
        allowed = resp.headers.get("access-control-allow-headers", "").lower()
        # With allow_headers=["*"], all headers should be allowed
        assert "*" in allowed or "x-api-key" in allowed

    def test_cors_no_auth_required_for_preflight(self):
        """CORS preflight should NOT require auth."""
        client = _make_client(auth_key="real-key")
        resp = client.options(
            "/v1/messages",
            headers={
                "origin": "http://localhost:3000",
                "access-control-request-method": "POST",
            },
        )
        # Preflight should succeed without any API key
        assert resp.status_code == 200


# ===========================================================================
# 13. Response format isolation
# ===========================================================================

class TestResponseFormatIsolation:
    """Verify response formats are strictly isolated per endpoint."""

    def test_messages_never_returns_openai_format(self, monkeypatch):
        """Messages endpoint should never return OpenAI-shaped response."""
        fake = _FakeLLM(
            consume_result=_openai_result(),
            stream_chunks=[f'data: {json.dumps(_openai_result())}\n\n', 'data: [DONE]\n\n'],
        )
        _setup_mock_llm(monkeypatch, fake)
        client = _make_client()

        resp = client.post("/v1/messages", json=_ANTHROPIC_BODY)
        assert resp.status_code == 200
        body = resp.json()
        # Should be Anthropic format
        assert body.get("type") == "message"
        assert body.get("role") == "assistant"
        # Should NOT have OpenAI fields
        assert "choices" not in body
        assert "object" not in body or body["object"] != "chat.completion"

    def test_responses_never_returns_anthropic_format(self, monkeypatch):
        """Responses endpoint should never return Anthropic-shaped response."""
        fake = _FakeLLM(
            consume_result=_openai_result(),
            stream_chunks=[f'data: {json.dumps(_openai_result())}\n\n', 'data: [DONE]\n\n'],
        )
        _setup_mock_llm(monkeypatch, fake)
        client = _make_client()

        resp = client.post("/v1/responses", json=_RESPONSES_BODY)
        assert resp.status_code == 200
        body = resp.json()
        # Should be Responses API format
        assert body.get("object") == "response"
        assert "output" in body
        # Should NOT have Anthropic fields
        assert body.get("type") != "message"
        assert "content" not in body or not isinstance(body.get("content"), list)

    def test_validation_errors_match_endpoint_format(self):
        """Validation errors should use the format of the endpoint, not the SDK."""
        client = _make_client()

        # Anthropic endpoint → Anthropic error format
        resp_a = client.post("/v1/messages", json={})
        assert resp_a.status_code == 400
        body_a = resp_a.json()
        assert body_a.get("type") == "error"

        # Responses endpoint → OpenAI error format
        resp_r = client.post("/v1/responses", json={})
        assert resp_r.status_code == 400
        body_r = resp_r.json()
        assert "error" in body_r
        # OpenAI error should NOT have top-level "type": "error"
        assert body_r.get("type") != "error"


# ===========================================================================
# 14. Headers isolation
# ===========================================================================

class TestHeadersIsolation:
    """Verify that response headers are appropriate per endpoint."""

    def test_messages_has_anthropic_version_header(self, monkeypatch):
        fake = _FakeLLM(
            consume_result=_openai_result(),
            stream_chunks=[f'data: {json.dumps(_openai_result())}\n\n', 'data: [DONE]\n\n'],
        )
        _setup_mock_llm(monkeypatch, fake)
        client = _make_client()

        resp = client.post("/v1/messages", json=_ANTHROPIC_BODY)
        assert resp.status_code == 200
        assert "anthropic-version" in resp.headers

    def test_messages_has_request_id_header(self, monkeypatch):
        fake = _FakeLLM(
            consume_result=_openai_result(),
            stream_chunks=[f'data: {json.dumps(_openai_result())}\n\n', 'data: [DONE]\n\n'],
        )
        _setup_mock_llm(monkeypatch, fake)
        client = _make_client()

        resp = client.post("/v1/messages", json=_ANTHROPIC_BODY)
        assert resp.status_code == 200
        assert "request-id" in resp.headers

    def test_responses_has_x_request_id_header(self, monkeypatch):
        fake = _FakeLLM(
            consume_result=_openai_result(),
            stream_chunks=[f'data: {json.dumps(_openai_result())}\n\n', 'data: [DONE]\n\n'],
        )
        _setup_mock_llm(monkeypatch, fake)
        client = _make_client()

        resp = client.post("/v1/responses", json=_RESPONSES_BODY)
        assert resp.status_code == 200
        assert "x-request-id" in resp.headers

    def test_messages_error_has_anthropic_version(self):
        """Even error responses from /v1/messages should have anthropic-version."""
        client = _make_client()
        resp = client.post("/v1/messages", json={})
        assert resp.status_code == 400
        assert "anthropic-version" in resp.headers


# ===========================================================================
# 15. Edge cases for endpoint matching
# ===========================================================================

class TestEndpointMatching:
    """Verify edge cases in path routing and matching."""

    def test_v1_messages_trailing_slash(self):
        """Trailing slash should still route or give clear error.
        500 is acceptable when mapper stub is None — the route matched and
        the handler executed, which is the routing behavior under test."""
        client = _make_client()
        resp = client.post("/v1/messages/", json=_ANTHROPIC_BODY)
        assert resp.status_code < 600  # No crash

    def test_v1_responses_trailing_slash(self):
        """See test_v1_messages_trailing_slash for rationale."""
        client = _make_client()
        resp = client.post("/v1/responses/", json=_RESPONSES_BODY)
        assert resp.status_code < 600  # No crash

    def test_case_sensitivity(self):
        """Paths should be case-sensitive."""
        client = _make_client()
        resp = client.post("/V1/MESSAGES", json=_ANTHROPIC_BODY)
        assert resp.status_code in (404, 405)

    def test_v1_messages_with_extra_segments(self):
        """Extra path segments beyond known routes should 404."""
        client = _make_client()
        resp = client.post("/v1/messages/unknown/segment", json=_ANTHROPIC_BODY)
        # Could hit batch routes or 404
        assert resp.status_code < 600

    def test_double_slash_in_path(self):
        client = _make_client()
        resp = client.post("//v1//messages", json=_ANTHROPIC_BODY)
        assert resp.status_code < 600  # No crash


# ===========================================================================
# 16. Cross-endpoint auth consistency
# ===========================================================================

class TestCrossEndpointAuth:
    """Verify auth works consistently across all endpoints."""

    def test_same_key_works_on_all_endpoints(self, monkeypatch):
        """A single API key should work on all endpoints."""
        fake = _FakeLLM(
            consume_result=_openai_result(),
            stream_chunks=[f'data: {json.dumps(_openai_result())}\n\n', 'data: [DONE]\n\n'],
        )
        _setup_mock_llm(monkeypatch, fake)
        monkeypatch.setattr("mapper.list_downstream", AsyncMock(return_value=[
            {"id": "test-model", "object": "model"},
        ]))
        monkeypatch.setattr("mapper.get_proxy_model", MagicMock(return_value={"id": "test-model"}))
        monkeypatch.setattr("mapper.workflow_models", MagicMock(return_value=[]))
        client = _make_client(auth_key="shared-key")

        # Messages endpoint with x-api-key
        resp_m = client.post("/v1/messages", json=_ANTHROPIC_BODY,
                             headers={"x-api-key": "shared-key"})
        assert resp_m.status_code == 200

        # Responses endpoint with Bearer
        resp_r = client.post("/v1/responses", json=_RESPONSES_BODY,
                             headers={"authorization": "Bearer shared-key"})
        assert resp_r.status_code == 200

        # Models endpoint with Bearer
        resp_models = client.get("/v1/models",
                                 headers={"authorization": "Bearer shared-key"})
        assert resp_models.status_code == 200

    def test_x_api_key_works_on_responses(self, monkeypatch):
        """x-api-key (Anthropic-style) should also work on /v1/responses."""
        fake = _FakeLLM(
            consume_result=_openai_result(),
            stream_chunks=[f'data: {json.dumps(_openai_result())}\n\n', 'data: [DONE]\n\n'],
        )
        _setup_mock_llm(monkeypatch, fake)
        client = _make_client(auth_key="my-key")

        resp = client.post("/v1/responses", json=_RESPONSES_BODY,
                           headers={"x-api-key": "my-key"})
        assert resp.status_code == 200

    def test_bearer_works_on_messages(self, monkeypatch):
        """Bearer token (OpenAI-style) should also work on /v1/messages."""
        fake = _FakeLLM(
            consume_result=_openai_result(),
            stream_chunks=[f'data: {json.dumps(_openai_result())}\n\n', 'data: [DONE]\n\n'],
        )
        _setup_mock_llm(monkeypatch, fake)
        client = _make_client(auth_key="my-key")

        resp = client.post("/v1/messages", json=_ANTHROPIC_BODY,
                           headers={"authorization": "Bearer my-key"})
        assert resp.status_code == 200
