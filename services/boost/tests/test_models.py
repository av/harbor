"""Tests for /v1/models and /v1/models/{model_id} endpoints.

Verifies that the models listing endpoint returns the correct format
for both OpenAI and Anthropic SDK clients, including proper response
headers and error handling.
"""

import pytest
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient
from fastapi import Request

import main
from compat_utils import ANTHROPIC_VERSION_HEADER, ANTHROPIC_VERSION

from helpers import make_request as _make_request


class TestIsAnthropicClient:
    def test_anthropic_version_header(self):
        req = _make_request({"anthropic-version": "2024-01-01"})
        assert main._is_anthropic_client(req) is True

    def test_x_api_key_without_authorization(self):
        req = _make_request({"x-api-key": "sk-ant-test"})
        assert main._is_anthropic_client(req) is True

    def test_x_api_key_with_authorization(self):
        req = _make_request({
            "x-api-key": "sk-ant-test",
            "authorization": "Bearer sk-other",
        })
        assert main._is_anthropic_client(req) is False

    def test_authorization_only(self):
        req = _make_request({"authorization": "Bearer sk-openai"})
        assert main._is_anthropic_client(req) is False

    def test_no_auth_headers(self):
        req = _make_request({})
        assert main._is_anthropic_client(req) is False

    def test_both_anthropic_version_and_authorization(self):
        req = _make_request({
            "anthropic-version": "2024-01-01",
            "authorization": "Bearer sk-test",
        })
        assert main._is_anthropic_client(req) is True


# ---------------------------------------------------------------------------
# Unit tests: _to_anthropic_model
# ---------------------------------------------------------------------------

class TestToAnthropicModel:
    def test_basic_conversion(self):
        model = {"id": "gpt-4", "object": "model", "created": 1234567890}
        result = main._to_anthropic_model(model)
        assert result["id"] == "gpt-4"
        assert result["type"] == "model"
        assert result["display_name"] == "gpt-4"
        assert result["created_at"] == "1970-01-01T00:00:00Z"

    def test_uses_name_for_display_name(self):
        model = {"id": "gpt-4", "name": "GPT-4 Turbo"}
        result = main._to_anthropic_model(model)
        assert result["display_name"] == "GPT-4 Turbo"

    def test_falls_back_to_id_for_display_name(self):
        model = {"id": "llama-3.1"}
        result = main._to_anthropic_model(model)
        assert result["display_name"] == "llama-3.1"

    def test_empty_model(self):
        result = main._to_anthropic_model({})
        assert result["id"] == ""
        assert result["type"] == "model"
        assert result["display_name"] == ""

    def test_no_extra_fields(self):
        model = {"id": "test", "object": "model", "created": 123, "owned_by": "org"}
        result = main._to_anthropic_model(model)
        assert set(result.keys()) == {"id", "type", "display_name", "created_at"}


# ---------------------------------------------------------------------------
# Integration tests: GET /v1/models
# ---------------------------------------------------------------------------

SAMPLE_MODELS = [
    {"id": "model-a", "object": "model", "created": 1700000000, "owned_by": "test"},
    {"id": "model-b", "object": "model", "created": 1700000001, "owned_by": "test"},
]


def _make_client():
    from helpers import make_client
    return make_client()


class TestModelsListOpenAI:
    """GET /v1/models with OpenAI-style client (Authorization header)."""

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_returns_openai_format(self, _wf, mock_downstream):
        mock_downstream.return_value = SAMPLE_MODELS
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get("/v1/models", headers={"authorization": "Bearer sk-test"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 2
        assert data["data"][0]["id"] == "model-a"
        assert "has_more" not in data

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_empty_models(self, _wf, mock_downstream):
        mock_downstream.return_value = []
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get("/v1/models", headers={"authorization": "Bearer sk-test"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert data["data"] == []


class TestModelsListAnthropic:
    """GET /v1/models with Anthropic-style client headers."""

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_returns_anthropic_format_with_version_header(self, _wf, mock_downstream):
        mock_downstream.return_value = SAMPLE_MODELS
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get("/v1/models", headers={"anthropic-version": "2024-01-01"})

        assert resp.status_code == 200
        data = resp.json()
        assert "object" not in data
        assert data["has_more"] is False
        assert data["first_id"] == "model-a"
        assert data["last_id"] == "model-b"
        assert len(data["data"]) == 2
        assert data["data"][0]["type"] == "model"
        assert data["data"][0]["id"] == "model-a"
        assert "display_name" in data["data"][0]
        assert "created_at" in data["data"][0]

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_returns_anthropic_format_with_x_api_key(self, _wf, mock_downstream):
        mock_downstream.return_value = SAMPLE_MODELS
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get("/v1/models", headers={"x-api-key": "sk-ant-test"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["has_more"] is False
        assert data["data"][0]["type"] == "model"

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_empty_models_anthropic(self, _wf, mock_downstream):
        mock_downstream.return_value = []
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get("/v1/models", headers={"anthropic-version": "2024-01-01"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"] == []
        assert data["has_more"] is False
        assert data["first_id"] is None
        assert data["last_id"] is None

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_model_display_name_uses_name_field(self, _wf, mock_downstream):
        mock_downstream.return_value = [
            {"id": "test-model", "object": "model", "name": "Test Model Display"},
        ]
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get("/v1/models", headers={"anthropic-version": "2024-01-01"})

        data = resp.json()
        assert data["data"][0]["display_name"] == "Test Model Display"


# ---------------------------------------------------------------------------
# Integration tests: GET /v1/models/{model_id}
# ---------------------------------------------------------------------------

class TestModelRetrieveOpenAI:
    """GET /v1/models/{model_id} with OpenAI-style client."""

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_returns_model(self, _wf, mock_downstream):
        mock_downstream.return_value = SAMPLE_MODELS
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get("/v1/models/model-a", headers={"authorization": "Bearer sk-test"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "model-a"
        assert data["object"] == "model"

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_not_found(self, _wf, mock_downstream):
        mock_downstream.return_value = SAMPLE_MODELS
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get("/v1/models/nonexistent", headers={"authorization": "Bearer sk-test"})

        assert resp.status_code == 404


class TestModelRetrieveAnthropic:
    """GET /v1/models/{model_id} with Anthropic-style client."""

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_returns_anthropic_format(self, _wf, mock_downstream):
        mock_downstream.return_value = SAMPLE_MODELS
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get(
            "/v1/models/model-a",
            headers={"anthropic-version": "2024-01-01"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "model-a"
        assert data["type"] == "model"
        assert "display_name" in data
        assert "created_at" in data
        assert "object" not in data

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_not_found_returns_anthropic_error(self, _wf, mock_downstream):
        mock_downstream.return_value = SAMPLE_MODELS
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get(
            "/v1/models/nonexistent",
            headers={"anthropic-version": "2024-01-01"},
        )

        assert resp.status_code == 404
        data = resp.json()
        assert data["type"] == "error"
        assert data["error"]["type"] == "not_found_error"

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_model_with_name(self, _wf, mock_downstream):
        mock_downstream.return_value = [
            {"id": "mod-x", "object": "model", "name": "Mod X Display"},
        ]
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get(
            "/v1/models/mod-x",
            headers={"anthropic-version": "2024-01-01"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["display_name"] == "Mod X Display"


# ---------------------------------------------------------------------------
# Anthropic response headers
# ---------------------------------------------------------------------------

class TestAnthropicModelHeaders:
    """Anthropic-format model responses include anthropic-version header."""

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_list_includes_version_header(self, _wf, mock_downstream):
        mock_downstream.return_value = SAMPLE_MODELS
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get("/v1/models", headers={"anthropic-version": "2024-01-01"})

        assert resp.status_code == 200
        assert resp.headers.get(ANTHROPIC_VERSION_HEADER) == ANTHROPIC_VERSION

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_retrieve_includes_version_header(self, _wf, mock_downstream):
        mock_downstream.return_value = SAMPLE_MODELS
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get(
            "/v1/models/model-a",
            headers={"anthropic-version": "2024-01-01"},
        )

        assert resp.status_code == 200
        assert resp.headers.get(ANTHROPIC_VERSION_HEADER) == ANTHROPIC_VERSION

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_not_found_includes_version_header(self, _wf, mock_downstream):
        mock_downstream.return_value = SAMPLE_MODELS
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get(
            "/v1/models/nonexistent",
            headers={"anthropic-version": "2024-01-01"},
        )

        assert resp.status_code == 404
        assert resp.headers.get(ANTHROPIC_VERSION_HEADER) == ANTHROPIC_VERSION

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_openai_client_no_anthropic_header(self, _wf, mock_downstream):
        mock_downstream.return_value = SAMPLE_MODELS
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get("/v1/models", headers={"authorization": "Bearer sk-test"})

        assert resp.status_code == 200
        assert resp.headers.get(ANTHROPIC_VERSION_HEADER) is None


# ---------------------------------------------------------------------------
# Error handling: _list_models failures
# ---------------------------------------------------------------------------

class TestModelsErrorHandling:
    """Models endpoints handle _list_models() failures gracefully."""

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_list_downstream_failure_anthropic(self, _wf, mock_downstream):
        mock_downstream.side_effect = Exception("Connection refused")
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get("/v1/models", headers={"anthropic-version": "2024-01-01"})

        assert resp.status_code == 500
        data = resp.json()
        assert data["type"] == "error"
        assert data["error"]["type"] == "api_error"
        assert resp.headers.get(ANTHROPIC_VERSION_HEADER) == ANTHROPIC_VERSION

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_list_downstream_failure_openai(self, _wf, mock_downstream):
        mock_downstream.side_effect = Exception("Connection refused")
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get("/v1/models", headers={"authorization": "Bearer sk-test"})

        assert resp.status_code == 500

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_retrieve_downstream_failure_anthropic(self, _wf, mock_downstream):
        mock_downstream.side_effect = Exception("Timeout")
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get(
            "/v1/models/some-model",
            headers={"anthropic-version": "2024-01-01"},
        )

        assert resp.status_code == 500
        data = resp.json()
        assert data["type"] == "error"
        assert data["error"]["type"] == "api_error"

    @patch.object(main.mapper, "list_downstream", new_callable=AsyncMock)
    @patch.object(main.mapper, "workflow_models", return_value=[])
    def test_retrieve_downstream_failure_openai(self, _wf, mock_downstream):
        mock_downstream.side_effect = Exception("Timeout")
        main.config.BOOST_MODS.__value__ = []
        main.config.SERVE_BASE_MODELS.__value__ = True
        main.config.MODEL_FILTER.__value__ = []

        client = _make_client()
        resp = client.get(
            "/v1/models/some-model",
            headers={"authorization": "Bearer sk-test"},
        )

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Global exception handler: SDK-format errors
# ---------------------------------------------------------------------------

class TestGlobalExceptionHandler:
    """HTTPExceptions raised by dependencies use SDK-appropriate error formats."""

    def test_anthropic_messages_path_auth_error(self):
        """Auth failure on /v1/messages returns Anthropic error format."""
        import config as _cfg
        _cfg.BOOST_AUTH = ["valid-key"]
        client = TestClient(main.app, raise_server_exceptions=False)

        resp = client.post(
            "/v1/messages",
            headers={"x-api-key": "wrong-key"},
            json={"model": "test", "max_tokens": 100, "messages": [{"role": "user", "content": "hi"}]},
        )

        assert resp.status_code == 401
        data = resp.json()
        assert data["type"] == "error"
        assert data["error"]["type"] == "authentication_error"
        assert resp.headers.get(ANTHROPIC_VERSION_HEADER) == ANTHROPIC_VERSION

        _cfg.BOOST_AUTH = []

    def test_responses_path_auth_error(self):
        """Auth failure on /v1/responses returns OpenAI error format."""
        import config as _cfg
        _cfg.BOOST_AUTH = ["valid-key"]
        client = TestClient(main.app, raise_server_exceptions=False)

        resp = client.post(
            "/v1/responses",
            headers={"authorization": "Bearer wrong-key"},
            json={"model": "test", "input": "hello"},
        )

        assert resp.status_code == 401
        data = resp.json()
        assert "error" in data
        assert data["error"]["type"] == "authentication_error"

        _cfg.BOOST_AUTH = []

    def test_anthropic_models_path_auth_error(self):
        """Auth failure on /v1/models with Anthropic headers returns Anthropic error format."""
        import config as _cfg
        _cfg.BOOST_AUTH = ["valid-key"]
        client = TestClient(main.app, raise_server_exceptions=False)

        resp = client.get(
            "/v1/models",
            headers={"anthropic-version": "2024-01-01", "x-api-key": "wrong-key"},
        )

        assert resp.status_code == 401
        data = resp.json()
        assert data["type"] == "error"
        assert data["error"]["type"] == "authentication_error"
        assert resp.headers.get(ANTHROPIC_VERSION_HEADER) == ANTHROPIC_VERSION

        _cfg.BOOST_AUTH = []

    def test_openai_models_path_auth_error(self):
        """Auth failure on /v1/models with OpenAI headers returns default format."""
        import config as _cfg
        _cfg.BOOST_AUTH = ["valid-key"]
        client = TestClient(main.app, raise_server_exceptions=False)

        resp = client.get(
            "/v1/models",
            headers={"authorization": "Bearer wrong-key"},
        )

        assert resp.status_code == 401
        data = resp.json()
        assert "detail" in data
        assert resp.headers.get(ANTHROPIC_VERSION_HEADER) is None

        _cfg.BOOST_AUTH = []
