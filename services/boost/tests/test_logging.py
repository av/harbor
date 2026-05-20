"""Tests for logging behavior across both compat layers and auth.

Verifies that:
- Error conditions produce appropriate log output with enough context
- Sensitive data (API keys, message content) is never logged
- Log levels are appropriate for each situation
"""

import json
import logging
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

import anthropic_compat
import responses_compat
import auth


@pytest.fixture(autouse=True)
def _enable_log_propagation():
    """Temporarily enable propagation on all Boost loggers so caplog can capture them.

    Boost's ``log.setup_logger`` sets ``propagate = False`` and adds a
    StreamHandler.  ``caplog`` captures via the root logger, so it never sees
    records from non-propagating loggers.  This fixture toggles propagation for
    the duration of each test.
    """
    logger_names = ["auth", "anthropic_compat", "responses_compat", "__main__"]
    originals = {}
    for name in logger_names:
        lg = logging.getLogger(name)
        originals[name] = lg.propagate
        lg.propagate = True
    yield
    for name, val in originals.items():
        logging.getLogger(name).propagate = val


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_request(headers=None):
    """Build a fake Starlette Request with the given headers."""
    from fastapi import Request

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


def _fake_openai_result(content="Hi!", finish_reason="stop",
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


class _FakeLLM:
    def __init__(self, consume_result=None, chat_completion_result=None,
                 stream_chunks=None, serve_error=None, **kwargs):
        self._consume_result = consume_result
        self._chat_completion_result = chat_completion_result
        self._stream_chunks = stream_chunks or []
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
        return self._chat_completion_result


def _make_anthropic_app():
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
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
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
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
    "messages": [{"role": "user", "content": "Hello, world!"}],
}

_RESPONSES_BODY = {
    "model": "gpt-4o",
    "input": "Hello, world!",
}


# ---------------------------------------------------------------------------
# Auth logging tests
# ---------------------------------------------------------------------------

class TestAuthLogging:
    """Verify auth.py logs auth outcomes appropriately."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", ["sk-valid-key"])

    @pytest.mark.asyncio
    async def test_failed_auth_logs_warning_no_key(self, caplog):
        """Missing API key should log a warning."""
        with caplog.at_level(logging.WARNING, logger="auth"):
            with pytest.raises(Exception):
                await auth.get_api_key(api_key_header=None, x_api_key=None)
        assert any("no API key provided" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_failed_auth_logs_warning_wrong_key(self, caplog):
        """Wrong API key should log a warning mentioning the header source."""
        with caplog.at_level(logging.WARNING, logger="auth"):
            with pytest.raises(Exception):
                await auth.get_api_key(api_key_header="Bearer sk-wrong", x_api_key=None)
        assert any("invalid key" in r.message for r in caplog.records)
        assert any("Authorization" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_failed_auth_does_not_log_key_value(self, caplog):
        """The actual key value must never appear in logs."""
        with caplog.at_level(logging.DEBUG, logger="auth"):
            with pytest.raises(Exception):
                await auth.get_api_key(api_key_header="Bearer sk-wrong-secret", x_api_key=None)
        for record in caplog.records:
            assert "sk-wrong-secret" not in record.message

    @pytest.mark.asyncio
    async def test_successful_auth_logs_debug(self, caplog):
        """Successful auth should log at DEBUG level."""
        with caplog.at_level(logging.DEBUG, logger="auth"):
            result = await auth.get_api_key(api_key_header="Bearer sk-valid-key", x_api_key=None)
        assert result == "sk-valid-key"
        assert any("Auth succeeded" in r.message for r in caplog.records)
        # The key value should not appear in the log
        for record in caplog.records:
            assert "sk-valid-key" not in record.message

    @pytest.mark.asyncio
    async def test_x_api_key_auth_logs_source(self, caplog):
        """Auth via x-api-key should mention that header in the log."""
        with caplog.at_level(logging.DEBUG, logger="auth"):
            result = await auth.get_api_key(api_key_header=None, x_api_key="sk-valid-key")
        assert result == "sk-valid-key"
        assert any("x-api-key" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Anthropic compat request/response logging
# ---------------------------------------------------------------------------

class TestAnthropicRequestLogging:
    """Verify request lifecycle logging in anthropic_compat."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])
        from fastapi.testclient import TestClient
        self.client = TestClient(_make_anthropic_app(), raise_server_exceptions=False)

    def test_request_logged_at_info(self, caplog):
        """Incoming request should be logged with model, stream, messages at INFO."""
        fake_llm = _FakeLLM(consume_result=_fake_openai_result())
        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
            caplog.at_level(logging.INFO, logger="anthropic_compat"),
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            self.client.post("/v1/messages", json=_ANTHRO_BODY)

        request_logs = [r for r in caplog.records if "Anthropic messages request" in r.message]
        assert len(request_logs) == 1
        log_msg = request_logs[0].message
        assert "model=claude-test" in log_msg
        assert "stream=False" in log_msg
        assert "messages=1" in log_msg

    def test_request_does_not_log_message_content(self, caplog):
        """Message body/content must not appear in logs."""
        fake_llm = _FakeLLM(consume_result=_fake_openai_result())
        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
            caplog.at_level(logging.DEBUG, logger="anthropic_compat"),
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            self.client.post("/v1/messages", json=_ANTHRO_BODY)

        for record in caplog.records:
            assert "Hello, world!" not in record.message

    def test_response_logged_with_stop_reason(self, caplog):
        """Non-streaming response should log the stop_reason."""
        fake_llm = _FakeLLM(consume_result=_fake_openai_result(finish_reason="stop"))
        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            patch.object(anthropic_compat, "llm_mod") as mock_llm_mod,
            caplog.at_level(logging.INFO, logger="anthropic_compat"),
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            self.client.post("/v1/messages", json=_ANTHRO_BODY)

        response_logs = [r for r in caplog.records if "Anthropic response" in r.message]
        assert len(response_logs) == 1
        assert "stop_reason=end_turn" in response_logs[0].message


class TestAnthropicErrorLogging:
    """Verify error logging in anthropic_compat."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])
        from fastapi.testclient import TestClient
        self.client = TestClient(_make_anthropic_app(), raise_server_exceptions=False)

    def test_value_error_logs_warning_with_context(self, caplog):
        """ValueError from mapper should log at WARNING with the error message."""
        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            caplog.at_level(logging.WARNING, logger="anthropic_compat"),
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(
                side_effect=ValueError("Unable to proxy request without a model specifier")
            )

            resp = self.client.post("/v1/messages", json=_ANTHRO_BODY)

        assert resp.status_code == 400
        warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_logs) >= 1
        assert any("validation error" in r.message for r in warning_logs)

    def test_unexpected_error_logs_error_with_exc_info(self, caplog):
        """Unexpected exceptions should log at ERROR with exc_info."""
        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            caplog.at_level(logging.ERROR, logger="anthropic_compat"),
        ):
            mock_mapper.list_downstream = AsyncMock(
                side_effect=RuntimeError("connection refused")
            )

            resp = self.client.post("/v1/messages", json=_ANTHRO_BODY)

        assert resp.status_code == 500
        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_logs) >= 1
        assert any("unexpected error" in r.message for r in error_logs)
        # exc_info should be present for unexpected errors
        assert any(r.exc_info is not None for r in error_logs)

    def test_5xx_error_does_not_leak_detail_to_client(self, caplog):
        """5xx errors should return generic message but log the real error."""
        with (
            patch.object(anthropic_compat, "mapper") as mock_mapper,
            caplog.at_level(logging.ERROR, logger="anthropic_compat"),
        ):
            mock_mapper.list_downstream = AsyncMock(
                side_effect=RuntimeError("secret backend url http://internal:8080")
            )

            resp = self.client.post("/v1/messages", json=_ANTHRO_BODY)

        body = resp.json()
        # Client should NOT see the internal URL
        assert "internal:8080" not in body["error"]["message"]
        assert body["error"]["message"] == "Internal server error"
        # But it should be in the server log
        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any("internal:8080" in r.message for r in error_logs)


# ---------------------------------------------------------------------------
# Responses compat request/response logging
# ---------------------------------------------------------------------------

class TestResponsesRequestLogging:
    """Verify request lifecycle logging in responses_compat."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])
        from fastapi.testclient import TestClient
        self.client = TestClient(_make_responses_app(), raise_server_exceptions=False)

    def test_request_logged_at_info(self, caplog):
        """Incoming request should be logged with model and stream flag at INFO."""
        fake_llm = _FakeLLM(consume_result=_fake_openai_result())
        with (
            patch.object(responses_compat, "mapper") as mock_mapper,
            patch.object(responses_compat, "llm_mod") as mock_llm_mod,
            caplog.at_level(logging.INFO, logger="responses_compat"),
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            self.client.post("/v1/responses", json=_RESPONSES_BODY)

        request_logs = [r for r in caplog.records if "Responses API request" in r.message]
        assert len(request_logs) == 1
        log_msg = request_logs[0].message
        assert "model=gpt-4o" in log_msg
        assert "stream=False" in log_msg

    def test_request_does_not_log_input_content(self, caplog):
        """Input content must not appear in logs."""
        fake_llm = _FakeLLM(consume_result=_fake_openai_result())
        with (
            patch.object(responses_compat, "mapper") as mock_mapper,
            patch.object(responses_compat, "llm_mod") as mock_llm_mod,
            caplog.at_level(logging.DEBUG, logger="responses_compat"),
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            self.client.post("/v1/responses", json=_RESPONSES_BODY)

        for record in caplog.records:
            assert "Hello, world!" not in record.message

    def test_response_logged_with_status(self, caplog):
        """Non-streaming response should log the status."""
        fake_llm = _FakeLLM(consume_result=_fake_openai_result(finish_reason="stop"))
        with (
            patch.object(responses_compat, "mapper") as mock_mapper,
            patch.object(responses_compat, "llm_mod") as mock_llm_mod,
            caplog.at_level(logging.INFO, logger="responses_compat"),
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(return_value={})
            mock_mapper.is_direct_task = MagicMock(return_value=False)
            mock_llm_mod.LLM = MagicMock(return_value=fake_llm)

            self.client.post("/v1/responses", json=_RESPONSES_BODY)

        response_logs = [r for r in caplog.records if "Responses API response" in r.message]
        assert len(response_logs) == 1
        assert "status=completed" in response_logs[0].message


class TestResponsesErrorLogging:
    """Verify error logging in responses_compat."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        import config as _cfg
        monkeypatch.setattr(_cfg, "BOOST_AUTH", [])
        from fastapi.testclient import TestClient
        self.client = TestClient(_make_responses_app(), raise_server_exceptions=False)

    def test_value_error_logs_warning(self, caplog):
        """ValueError should log at WARNING."""
        with (
            patch.object(responses_compat, "mapper") as mock_mapper,
            caplog.at_level(logging.WARNING, logger="responses_compat"),
        ):
            mock_mapper.list_downstream = AsyncMock()
            mock_mapper.resolve_request_config = MagicMock(
                side_effect=ValueError("Unable to proxy request")
            )

            resp = self.client.post("/v1/responses", json=_RESPONSES_BODY)

        assert resp.status_code == 400
        warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("validation error" in r.message for r in warning_logs)

    def test_unexpected_error_logs_error_with_exc_info(self, caplog):
        """Unexpected exceptions should log at ERROR with exc_info."""
        with (
            patch.object(responses_compat, "mapper") as mock_mapper,
            caplog.at_level(logging.ERROR, logger="responses_compat"),
        ):
            mock_mapper.list_downstream = AsyncMock(
                side_effect=RuntimeError("connection refused")
            )

            resp = self.client.post("/v1/responses", json=_RESPONSES_BODY)

        assert resp.status_code == 500
        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any("unexpected error" in r.message for r in error_logs)
        assert any(r.exc_info is not None for r in error_logs)

    def test_5xx_error_does_not_leak_detail_to_client(self, caplog):
        """5xx errors should return generic message but log the real error."""
        with (
            patch.object(responses_compat, "mapper") as mock_mapper,
            caplog.at_level(logging.ERROR, logger="responses_compat"),
        ):
            mock_mapper.list_downstream = AsyncMock(
                side_effect=RuntimeError("secret at http://internal:9090/path")
            )

            resp = self.client.post("/v1/responses", json=_RESPONSES_BODY)

        body = resp.json()
        assert "internal:9090" not in body["error"]["message"]
        assert body["error"]["message"] == "Internal server error"
        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any("internal:9090" in r.message for r in error_logs)


# ---------------------------------------------------------------------------
# Log level appropriateness
# ---------------------------------------------------------------------------

class TestLogLevels:
    """Verify log levels are appropriate across the codebase."""

    def test_beta_flags_logged_at_debug(self, caplog):
        """Beta flag parsing should be at DEBUG, not INFO."""
        request = make_request({"anthropic-beta": "prompt-caching-2024-07-31,unknown-flag"})
        with caplog.at_level(logging.DEBUG, logger="anthropic_compat"):
            result = anthropic_compat._parse_beta_flags(request)
        # Should see debug logs for both recognized and unrecognized flags
        assert any("anthropic-beta flags" in r.message for r in caplog.records)
        assert any("unrecognized beta flags" in r.message for r in caplog.records)
        # All beta flag logs should be at DEBUG level
        beta_logs = [r for r in caplog.records if "beta" in r.message.lower()]
        for log_record in beta_logs:
            assert log_record.levelno == logging.DEBUG

    def test_document_fallback_logged_at_warning(self, caplog):
        """Document content block fallbacks should be at WARNING."""
        content = [{"type": "document", "source": {"type": "url", "url": "https://example.com/doc.pdf"}}]
        with caplog.at_level(logging.WARNING, logger="anthropic_compat"):
            anthropic_compat._convert_user_message(content)
        warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_logs) >= 1
        assert any("Document URL" in r.message for r in warning_logs)

    def test_unsupported_tool_logged_at_warning(self, caplog):
        """Unsupported tool types should be at WARNING."""
        body = {"tools": [{"type": "file_search"}]}
        with caplog.at_level(logging.WARNING, logger="responses_compat"):
            responses_compat._convert_tools(body)
        warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("file_search" in r.message for r in warning_logs)

    def test_skipped_input_items_logged_at_debug(self, caplog):
        """Skipped input items (reasoning, computer_call_output) should be at DEBUG."""
        body = {"input": [{"type": "reasoning", "id": "r1", "summary": []}]}
        with caplog.at_level(logging.DEBUG, logger="responses_compat"):
            responses_compat._convert_input_to_messages(body)
        debug_logs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("reasoning" in r.message for r in debug_logs)


# ---------------------------------------------------------------------------
# Sensitive data protection
# ---------------------------------------------------------------------------

class TestSensitiveDataProtection:
    """Verify sensitive data never appears in logs."""

    def test_api_key_never_in_anthropic_error_log(self, caplog):
        """API keys from x-api-key header must not be logged."""
        request = make_request({"x-api-key": "sk-secret-anthropic-key-12345"})
        with caplog.at_level(logging.DEBUG, logger="anthropic_compat"):
            anthropic_compat._synthesize_authorization(request)
        for record in caplog.records:
            assert "sk-secret-anthropic-key-12345" not in record.message

    def test_auth_failure_does_not_log_bearer_token(self, caplog):
        """Auth failure for wrong Bearer token must not log the token."""
        import config as _cfg
        original = _cfg.BOOST_AUTH
        _cfg.BOOST_AUTH = ["sk-correct"]
        try:
            with caplog.at_level(logging.DEBUG, logger="auth"):
                with pytest.raises(Exception):
                    import asyncio
                    asyncio.get_event_loop().run_until_complete(
                        auth.get_api_key(api_key_header="Bearer sk-my-secret-token", x_api_key=None)
                    )
            for record in caplog.records:
                assert "sk-my-secret-token" not in record.message
        finally:
            _cfg.BOOST_AUTH = original
