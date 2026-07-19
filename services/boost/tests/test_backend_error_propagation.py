"""Backend error propagation through /v1/chat/completions.

When the backend rejects a chat completion (e.g. llamacpp 400
exceed_context_size_error), Boost must not answer 200 with empty content:

- Non-streaming: respond with the backend's status code and an
  OpenAI-style {"error": {...}} JSON carrying the backend's message.
- Streaming: if the failure happens before any chunk is yielded (headers
  not yet committed), same as non-streaming; if it happens mid-stream,
  emit a final SSE error chunk followed by [DONE].
- Module/workflow catch-alls in LLM.serve() re-raise BackendError so it
  reaches the response layer; other exceptions keep the previous
  degraded-but-200 behavior (internal recoveries keep working).
"""

import json

import pytest
from unittest.mock import AsyncMock

import llm as llm_mod
from llm import BackendError
import main

from helpers import (
    FakeLLM,
    make_client,
    setup_mock_llm,
)


LLAMACPP_400_BODY = json.dumps({
    "error": {
        "code": 400,
        "message": "the request exceeds the available context size",
        "type": "exceed_context_size_error",
    }
})


def _chat_body(stream=False):
    return {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": stream,
    }


class RaisingStreamLLM(FakeLLM):
    """FakeLLM whose served stream optionally yields chunks then raises."""

    def __init__(self, error, pre_chunks=None, **kwargs):
        super().__init__(**kwargs)
        self._error = error
        self._pre_chunks = pre_chunks or []

    async def serve(self):
        async def _gen():
            for chunk in self._pre_chunks:
                yield chunk
            raise self._error
        return _gen()

    async def consume_stream(self, stream):
        async for _ in stream:
            pass
        return self._consume_result


# ===========================================================================
# Non-streaming
# ===========================================================================

class TestNonStreamingPropagation:

    def test_backend_400_propagates_status_and_error_json(self, monkeypatch):
        fake = RaisingStreamLLM(BackendError(400, LLAMACPP_400_BODY))
        setup_mock_llm(monkeypatch, fake)

        resp = make_client().post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["type"] == "exceed_context_size_error"
        assert "context size" in body["error"]["message"]

    def test_backend_500_non_json_body_wrapped(self, monkeypatch):
        fake = RaisingStreamLLM(BackendError(502, "upstream connection refused"))
        setup_mock_llm(monkeypatch, fake)

        resp = make_client().post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 502
        body = resp.json()
        assert body["error"]["message"] == "upstream connection refused"
        assert body["error"]["type"] == "upstream_error"
        assert body["error"]["code"] == 502

    def test_backend_error_empty_body_generic_message(self, monkeypatch):
        fake = RaisingStreamLLM(BackendError(500, ""))
        setup_mock_llm(monkeypatch, fake)

        resp = make_client().post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 500
        assert resp.json()["error"]["message"] == "Backend request failed"

    def test_rate_limit_headers_forwarded(self, monkeypatch):
        fake = RaisingStreamLLM(
            BackendError(429, "rate limited", {"retry-after": "30"})
        )
        setup_mock_llm(monkeypatch, fake)

        resp = make_client().post("/v1/chat/completions", json=_chat_body())
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == "30"


# ===========================================================================
# Streaming
# ===========================================================================

class TestStreamingPropagation:

    def test_error_before_first_chunk_propagates_status(self, monkeypatch):
        """Headers not committed yet: client gets the backend's status."""
        fake = RaisingStreamLLM(BackendError(400, LLAMACPP_400_BODY))
        setup_mock_llm(monkeypatch, fake)

        resp = make_client().post("/v1/chat/completions", json=_chat_body(stream=True))
        assert resp.status_code == 400
        assert resp.json()["error"]["type"] == "exceed_context_size_error"

    def test_error_mid_stream_emits_error_chunk_and_done(self, monkeypatch):
        """Already streaming: error is carried as a final SSE chunk."""
        first = 'data: {"choices": [{"delta": {"content": "partial"}, "index": 0}]}\n\n'
        fake = RaisingStreamLLM(
            BackendError(400, LLAMACPP_400_BODY), pre_chunks=[first]
        )
        setup_mock_llm(monkeypatch, fake)

        resp = make_client().post("/v1/chat/completions", json=_chat_body(stream=True))
        assert resp.status_code == 200
        text = resp.text
        assert "partial" in text
        assert "exceed_context_size_error" in text
        assert text.rstrip().endswith("data: [DONE]")

    def test_successful_stream_unchanged(self, monkeypatch):
        chunks = [
            'data: {"choices": [{"delta": {"content": "Hi"}, "index": 0}]}\n\n',
            "data: [DONE]\n\n",
        ]
        fake = FakeLLM(stream_chunks=chunks)
        setup_mock_llm(monkeypatch, fake)

        resp = make_client().post("/v1/chat/completions", json=_chat_body(stream=True))
        assert resp.status_code == 200
        assert "Hi" in resp.text


# ===========================================================================
# LLM.serve() re-raise semantics
# ===========================================================================

def _make_llm(module=None, workflow=None):
    return llm_mod.LLM(
        url="http://fake:8080",
        model="test-model",
        module=module,
        workflow=workflow,
        messages=[{"role": "user", "content": "hi"}],
        params={},
    )


class TestServeReraise:

    @pytest.mark.asyncio
    async def test_module_backend_error_reaches_generator(self, monkeypatch):
        """A BackendError escaping a module aborts the stream with the error."""
        proxy = _make_llm(module="broken")

        class BrokenMod:
            async def apply(self, chat, llm):
                raise BackendError(400, LLAMACPP_400_BODY)

        import mods
        monkeypatch.setitem(mods.registry, "broken", BrokenMod())

        stream = await proxy.serve()
        with pytest.raises(BackendError) as exc_info:
            async for _ in stream:
                pass
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_module_generic_error_still_recovers(self, monkeypatch):
        """Non-backend module errors keep the degraded 200 behavior."""
        proxy = _make_llm(module="broken")

        class BrokenMod:
            async def apply(self, chat, llm):
                raise ValueError("internal module bug")

        import mods
        monkeypatch.setitem(mods.registry, "broken", BrokenMod())

        stream = await proxy.serve()
        chunks = [c async for c in stream]
        assert isinstance(chunks, list)  # completes without raising

    @pytest.mark.asyncio
    async def test_module_internal_recovery_not_propagated(self, monkeypatch):
        """Modules that catch BackendError internally still produce output."""
        proxy = _make_llm(module="resilient")

        class ResilientMod:
            async def apply(self, chat, llm):
                try:
                    raise BackendError(500, "transient")
                except BackendError:
                    llm.is_final_stream = True
                    await llm.emit_message("recovered")

        import mods
        monkeypatch.setitem(mods.registry, "resilient", ResilientMod())

        stream = await proxy.serve()
        chunks = [c async for c in stream]
        assert any("recovered" in str(c) for c in chunks)

    @pytest.mark.asyncio
    async def test_workflow_backend_error_reaches_generator(self, monkeypatch):
        proxy = _make_llm(workflow={"name": "x"})

        async def broken_workflow(workflow, chat, llm):
            raise BackendError(429, "rate limited", {"retry-after": "5"})

        monkeypatch.setattr("workflows.apply_workflow", broken_workflow)

        stream = await proxy.serve()
        with pytest.raises(BackendError) as exc_info:
            async for _ in stream:
                pass
        assert exc_info.value.status_code == 429
