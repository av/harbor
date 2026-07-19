"""Concise logging for handled BackendErrors.

Handled backend failures (e.g. llamacpp 400 exceed_context_size_error) must
log exactly one concise "Backend error <status>: <message>" line without any
stack-trace frames. Unhandled/unexpected exceptions must still log full
tracebacks.
"""

import json
import logging

import httpx
import pytest

import llm as llm_mod
import mods
from llm import BackendError


LLAMACPP_400_BODY = json.dumps({
    "error": {
        "code": 400,
        "message": "the request exceeds the available context size",
        "type": "exceed_context_size_error",
    }
})


@pytest.fixture
def llm_caplog(caplog):
    """caplog wired to boost's non-propagating 'llm' logger."""
    logger = logging.getLogger("llm")
    old = logger.propagate
    logger.propagate = True
    caplog.set_level(logging.DEBUG, logger="llm")
    yield caplog
    logger.propagate = old


def _make_llm(module=None, workflow=None):
    return llm_mod.LLM(
        url="http://fake:8080",
        model="test-model",
        module=module,
        workflow=workflow,
        messages=[{"role": "user", "content": "hi"}],
        params={},
    )


def _mock_backend_400(monkeypatch):
    def _handler(request):
        return httpx.Response(400, text=LLAMACPP_400_BODY)

    transport = httpx.MockTransport(_handler)
    orig_client = httpx.AsyncClient

    def _client(**kwargs):
        kwargs.pop("transport", None)
        return orig_client(transport=transport, **kwargs)

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _client)


class TestHandledBackendErrorLogging:

    @pytest.mark.asyncio
    async def test_chat_completion_400_logs_one_concise_line(
        self, monkeypatch, llm_caplog
    ):
        """Raise site logs 'Backend error 400: ...' — no traceback frames."""
        _mock_backend_400(monkeypatch)
        proxy = _make_llm()

        with pytest.raises(BackendError):
            await proxy.chat_completion()

        concise = [
            r for r in llm_caplog.records if r.getMessage().startswith("Backend error 400")
        ]
        assert len(concise) == 1
        assert "context size" in concise[0].getMessage()
        assert concise[0].exc_info is None
        assert "Traceback" not in llm_caplog.text

    @pytest.mark.asyncio
    async def test_module_backend_error_no_traceback_in_serve(
        self, monkeypatch, llm_caplog
    ):
        """BackendError escaping a module: no exc_info records, no frames."""
        proxy = _make_llm(module="broken")

        class BrokenMod:
            async def apply(self, chat, llm):
                raise BackendError(400, LLAMACPP_400_BODY)

        monkeypatch.setitem(mods.registry, "broken", BrokenMod())

        stream = await proxy.serve()
        with pytest.raises(BackendError):
            async for _ in stream:
                pass

        assert "Traceback" not in llm_caplog.text
        assert not any(r.exc_info for r in llm_caplog.records)
        assert not any(
            r.levelno >= logging.ERROR for r in llm_caplog.records
        ), "handled BackendError must not log at ERROR"


class TestUnexpectedErrorLogging:

    @pytest.mark.asyncio
    async def test_unexpected_exception_logs_traceback(
        self, monkeypatch, llm_caplog
    ):
        """A non-BackendError escaping apply_mod still gets full exc_info."""
        proxy = _make_llm(module="whatever")

        class ExplodingRegistry:
            def get(self, name):
                raise RuntimeError("unexpected internal failure")

        monkeypatch.setattr(mods, "registry", ExplodingRegistry())

        stream = await proxy.serve()
        with pytest.raises(RuntimeError):
            async for _ in stream:
                pass

        failed = [
            r for r in llm_caplog.records
            if r.levelno >= logging.ERROR and r.exc_info
        ]
        assert len(failed) == 1
        assert "Traceback" in llm_caplog.text
