"""Shared test helpers for Boost tests.

Centralizes common test utilities that were previously duplicated across
multiple test files: FakeLLM, request/response builders, SSE parsers,
app construction, and mock setup.
"""

import json
from unittest.mock import MagicMock, AsyncMock

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# FakeLLM — drop-in replacement for llm.LLM in test contexts
# ---------------------------------------------------------------------------

class FakeLLM:
    """Minimal stand-in for llm.LLM.

    Supports configurable stream chunks, consume results, chat completion
    results, and optional serve-time errors.
    """

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
            from llm import BackendError
            raise BackendError(500, "no result configured")
        return self._chat_completion_result


# ---------------------------------------------------------------------------
# Request builders
# ---------------------------------------------------------------------------

def make_request(headers=None):
    """Build a fake Starlette Request with the given headers."""
    raw_headers = [(b"content-type", b"application/json")]
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), value.encode()))
    return Request(
        scope={
            "type": "http",
            "query_string": b"",
            "headers": raw_headers,
        }
    )


# ---------------------------------------------------------------------------
# OpenAI-shaped response builders
# ---------------------------------------------------------------------------

def openai_result(content="Hello!", finish_reason="stop",
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
        "choices": [{
            "index": 0,
            "message": msg,
            "finish_reason": finish_reason,
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def streaming_chunks(content="Hello!", finish_reason="stop",
                     prompt_tokens=10, completion_tokens=5):
    """Build a list of stringified SSE chunks as LLM.serve() yields them."""
    chunks = []
    for char in content:
        chunks.append(
            f'data: {json.dumps({"choices": [{"delta": {"content": char}, "index": 0}]})}\n\n'
        )
    chunks.append(
        f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": finish_reason, "index": 0}], "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens}})}\n\n'
    )
    chunks.append("data: [DONE]\n\n")
    return chunks


def sse_chunk(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# SSE event parsers
# ---------------------------------------------------------------------------

def parse_anthropic_sse_events(raw_text):
    """Parse raw SSE text into a list of Anthropic data payloads (dicts).

    Skips ``event: ping`` keepalive frames so callers can assert message
    event ordering only.
    """
    events = []
    for block in raw_text.strip().split("\n\n"):
        event_type = None
        data_line = None
        for line in block.strip().split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            if line.startswith("data: "):
                data_line = line[6:]
        if event_type == "ping":
            continue
        if data_line:
            try:
                parsed = json.loads(data_line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and "type" not in parsed:
                continue
            events.append(parsed)
    return events


def parse_responses_sse_events(raw_events):
    """Parse Responses API SSE strings into (event_type, data_dict) tuples."""
    parsed = []
    for raw in raw_events:
        lines = raw.strip().split("\n")
        event_type = None
        data_str = None
        for line in lines:
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
        if event_type and data_str:
            parsed.append((event_type, json.loads(data_str)))
    return parsed


# ---------------------------------------------------------------------------
# App construction
# ---------------------------------------------------------------------------

def make_anthropic_app():
    """Build a test FastAPI app with the Anthropic router and error handler."""
    import anthropic_compat

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


def make_responses_app():
    """Build a test FastAPI app with the Responses router and error handler."""
    import responses_compat

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


def make_full_app():
    """Return the fully configured app from main.py."""
    import main
    return main.app


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------

def make_client(app=None, auth_key=None):
    """Return a TestClient with optional auth configuration.

    When *app* is None, uses the full main.app.
    """
    import config as _cfg
    if auth_key:
        _cfg.BOOST_AUTH = [auth_key]
    else:
        _cfg.BOOST_AUTH = []
    if app is None:
        app = make_full_app()
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Agentic / autocheck cheap-LLM mocks
# ---------------------------------------------------------------------------

def mock_cheap_llm(
    *,
    chat_completion=None,
    stream_chat_completion=None,
) -> MagicMock:
    """Build a MagicMock returned by ``research.orchestrate.cheap_llm``."""
    cheap = MagicMock()
    if chat_completion is not None:
        cheap.chat_completion = chat_completion
    if stream_chat_completion is not None:
        cheap.stream_chat_completion = stream_chat_completion
    return cheap


def mock_autocheck_cheap_llm(
    *,
    draft_response: str = "Draft implementation",
    draft_side_effect=None,
    audit_response=None,
) -> MagicMock:
    """Mock cheap client for autocheck draft (stream) and audit (chat) sub-calls."""
    if draft_side_effect is not None:
        stream_chat_completion = AsyncMock(side_effect=draft_side_effect)
    else:
        stream_chat_completion = AsyncMock(return_value=draft_response)
    chat_completion = AsyncMock(
        return_value=audit_response or {
            "verdict": "pass",
            "summary": "Ship it",
            "findings": [],
        },
    )
    return mock_cheap_llm(
        chat_completion=chat_completion,
        stream_chat_completion=stream_chat_completion,
    )


# ---------------------------------------------------------------------------
# Mock setup
# ---------------------------------------------------------------------------

def setup_mock_llm(monkeypatch, llm_instance, is_direct=False):
    """Patch mapper and llm modules to return the given FakeLLM instance."""
    import llm as llm_mod
    monkeypatch.setattr("mapper.list_downstream", AsyncMock(return_value=[]))
    monkeypatch.setattr("mapper.resolve_request_config", MagicMock(return_value={
        "url": "http://fake:8080",
        "api_key": "sk-test",
        "headers": {"Authorization": "Bearer sk-test"},
        "model": "test-model",
        "module": None,
        "workflow": None,
        "params": {},
    }))
    monkeypatch.setattr("mapper.is_direct_task", MagicMock(return_value=is_direct))
    monkeypatch.setattr(llm_mod, "LLM", lambda **kwargs: llm_instance)


# ---------------------------------------------------------------------------
# Canonical request bodies
# ---------------------------------------------------------------------------

ANTHROPIC_BODY = {
    "model": "claude-test",
    "max_tokens": 128,
    "messages": [{"role": "user", "content": "Hello, world!"}],
}

RESPONSES_BODY = {
    "model": "gpt-4o",
    "input": "Hello, world!",
}

CHAT_COMPLETIONS_BODY = {
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}],
}
