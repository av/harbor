"""Tests for config-driven compat layer behavior.

Verifies that ENABLE_ANTHROPIC_COMPAT and ENABLE_RESPONSES_API control router
registration correctly: endpoints return 404 when their layer is disabled,
/v1/chat/completions and /v1/models always work, and config defaults/env
parsing are correct.
"""

import json
import os
import sys
import types
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Config unit tests (no app import needed)
# ---------------------------------------------------------------------------

class TestConfigDefaults:
    """Default values for compat config flags."""

    def _reload_config(self, env_overrides=None):
        """Reload config module with optional env var overrides."""
        orig = sys.modules.get("config")
        try:
            if "config" in sys.modules:
                del sys.modules["config"]
            with patch.dict(os.environ, env_overrides or {}, clear=False):
                import config
                return config
        finally:
            if orig is not None:
                sys.modules["config"] = orig
            elif "config" in sys.modules:
                del sys.modules["config"]

    def test_anthropic_compat_defaults_true(self):
        """ENABLE_ANTHROPIC_COMPAT defaults to True when env var is unset."""
        env = os.environ.copy()
        env.pop("HARBOR_BOOST_ANTHROPIC_COMPAT", None)
        if "config" in sys.modules:
            orig = sys.modules["config"]
        else:
            orig = None
        try:
            if "config" in sys.modules:
                del sys.modules["config"]
            with patch.dict(os.environ, env, clear=True):
                import config
                assert config.ENABLE_ANTHROPIC_COMPAT.value is True
        finally:
            if orig is not None:
                sys.modules["config"] = orig
            elif "config" in sys.modules:
                del sys.modules["config"]

    def test_responses_api_defaults_true(self):
        """ENABLE_RESPONSES_API defaults to True when env var is unset."""
        env = os.environ.copy()
        env.pop("HARBOR_BOOST_RESPONSES_API", None)
        if "config" in sys.modules:
            orig = sys.modules["config"]
        else:
            orig = None
        try:
            if "config" in sys.modules:
                del sys.modules["config"]
            with patch.dict(os.environ, env, clear=True):
                import config
                assert config.ENABLE_RESPONSES_API.value is True
        finally:
            if orig is not None:
                sys.modules["config"] = orig
            elif "config" in sys.modules:
                del sys.modules["config"]

    def test_anthropic_compat_env_name(self):
        """Config reads from HARBOR_BOOST_ANTHROPIC_COMPAT env var."""
        if "config" in sys.modules:
            orig = sys.modules["config"]
        else:
            orig = None
        try:
            if "config" in sys.modules:
                del sys.modules["config"]
            with patch.dict(os.environ, {"HARBOR_BOOST_ANTHROPIC_COMPAT": "false"}, clear=False):
                import config
                assert config.ENABLE_ANTHROPIC_COMPAT.value is False
                assert config.ENABLE_ANTHROPIC_COMPAT.name == "HARBOR_BOOST_ANTHROPIC_COMPAT"
        finally:
            if orig is not None:
                sys.modules["config"] = orig
            elif "config" in sys.modules:
                del sys.modules["config"]

    def test_responses_api_env_name(self):
        """Config reads from HARBOR_BOOST_RESPONSES_API env var."""
        if "config" in sys.modules:
            orig = sys.modules["config"]
        else:
            orig = None
        try:
            if "config" in sys.modules:
                del sys.modules["config"]
            with patch.dict(os.environ, {"HARBOR_BOOST_RESPONSES_API": "false"}, clear=False):
                import config
                assert config.ENABLE_RESPONSES_API.value is False
                assert config.ENABLE_RESPONSES_API.name == "HARBOR_BOOST_RESPONSES_API"
        finally:
            if orig is not None:
                sys.modules["config"] = orig
            elif "config" in sys.modules:
                del sys.modules["config"]


class TestConfigBoolParsing:
    """Bool config parsing for various string inputs."""

    def _reload_config_with(self, key, value):
        orig = sys.modules.get("config")
        try:
            if "config" in sys.modules:
                del sys.modules["config"]
            with patch.dict(os.environ, {key: value}, clear=False):
                import config
                return config
        finally:
            if orig is not None:
                sys.modules["config"] = orig
            elif "config" in sys.modules:
                del sys.modules["config"]

    def test_true_string(self):
        cfg = self._reload_config_with("HARBOR_BOOST_ANTHROPIC_COMPAT", "true")
        assert cfg.ENABLE_ANTHROPIC_COMPAT.value is True

    def test_false_string(self):
        cfg = self._reload_config_with("HARBOR_BOOST_ANTHROPIC_COMPAT", "false")
        assert cfg.ENABLE_ANTHROPIC_COMPAT.value is False

    def test_one_is_true(self):
        cfg = self._reload_config_with("HARBOR_BOOST_ANTHROPIC_COMPAT", "1")
        assert cfg.ENABLE_ANTHROPIC_COMPAT.value is True

    def test_zero_is_false(self):
        cfg = self._reload_config_with("HARBOR_BOOST_ANTHROPIC_COMPAT", "0")
        assert cfg.ENABLE_ANTHROPIC_COMPAT.value is False

    def test_yes_is_true(self):
        cfg = self._reload_config_with("HARBOR_BOOST_ANTHROPIC_COMPAT", "yes")
        assert cfg.ENABLE_ANTHROPIC_COMPAT.value is True

    def test_on_is_true(self):
        cfg = self._reload_config_with("HARBOR_BOOST_ANTHROPIC_COMPAT", "on")
        assert cfg.ENABLE_ANTHROPIC_COMPAT.value is True

    def test_TRUE_uppercase(self):
        cfg = self._reload_config_with("HARBOR_BOOST_ANTHROPIC_COMPAT", "TRUE")
        assert cfg.ENABLE_ANTHROPIC_COMPAT.value is True

    def test_False_mixed_case(self):
        cfg = self._reload_config_with("HARBOR_BOOST_ANTHROPIC_COMPAT", "False")
        assert cfg.ENABLE_ANTHROPIC_COMPAT.value is False

    def test_random_string_is_false(self):
        """Non-boolean strings resolve to False (not true/1/yes/on)."""
        cfg = self._reload_config_with("HARBOR_BOOST_ANTHROPIC_COMPAT", "banana")
        assert cfg.ENABLE_ANTHROPIC_COMPAT.value is False

    def test_empty_string_is_false(self):
        cfg = self._reload_config_with("HARBOR_BOOST_ANTHROPIC_COMPAT", "")
        assert cfg.ENABLE_ANTHROPIC_COMPAT.value is False

    def test_responses_api_same_parsing(self):
        """ENABLE_RESPONSES_API uses the same bool parsing."""
        cfg = self._reload_config_with("HARBOR_BOOST_RESPONSES_API", "false")
        assert cfg.ENABLE_RESPONSES_API.value is False
        cfg2 = self._reload_config_with("HARBOR_BOOST_RESPONSES_API", "1")
        assert cfg2.ENABLE_RESPONSES_API.value is True


class TestConfigResolvedAtImportTime:
    """Config values are resolved once at import time, not per-request."""

    def test_value_resolved_at_init(self):
        """Config.__init__ calls resolve_value() and caches the result."""
        from config import Config
        cfg = Config("TEST_VAR_NOT_SET", bool, "true")
        assert cfg.value is True
        # Changing the env after init has no effect
        os.environ["TEST_VAR_NOT_SET"] = "false"
        assert cfg.value is True
        os.environ.pop("TEST_VAR_NOT_SET", None)

    def test_value_is_property_not_function(self):
        """Config.value is a property returning the cached __value__."""
        from config import Config
        cfg = Config("TEST_PROP_CHECK", bool, "false")
        assert cfg.value is cfg.__value__
        assert cfg.value is False


# ---------------------------------------------------------------------------
# Router registration tests — require reloading main with different configs
# ---------------------------------------------------------------------------

def _make_fresh_app(anthropic_compat="true", responses_api="true"):
    """Create a fresh FastAPI app with the given compat layer config.

    Reloads config and main modules so that the module-level ``if`` guards
    in main.py re-evaluate with the new environment.
    """
    from starlette.testclient import TestClient

    # Preserve original modules to restore later
    saved = {}
    for mod_name in ("config", "main", "anthropic_compat", "responses_compat",
                     "auth", "compat_utils", "selection", "mods",
                     "llm_registry"):
        saved[mod_name] = sys.modules.get(mod_name)

    env_patch = {
        "HARBOR_BOOST_ANTHROPIC_COMPAT": anthropic_compat,
        "HARBOR_BOOST_RESPONSES_API": responses_api,
    }

    # Remove modules that need reloading
    for mod_name in ("config", "main", "anthropic_compat", "responses_compat"):
        sys.modules.pop(mod_name, None)

    with patch.dict(os.environ, env_patch, clear=False):
        import config as cfg
        cfg.BOOST_AUTH = []  # disable auth for tests

        import main as main_mod

    client = TestClient(main_mod.app, raise_server_exceptions=False)

    # Restore original modules for test isolation
    def restore():
        for mod_name, mod in saved.items():
            if mod is not None:
                sys.modules[mod_name] = mod
            else:
                sys.modules.pop(mod_name, None)

    return client, main_mod, restore


class TestAnthropicCompatDisabled:
    """When ENABLE_ANTHROPIC_COMPAT is false, /v1/messages is not registered."""

    def test_messages_returns_404(self):
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="true"
        )
        try:
            resp = client.post(
                "/v1/messages",
                json={
                    "model": "test-model",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                headers={"x-api-key": "test"},
            )
            assert resp.status_code in (404, 405), (
                f"Expected 404/405 when Anthropic compat disabled, got {resp.status_code}"
            )
        finally:
            restore()

    def test_count_tokens_returns_404(self):
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="true"
        )
        try:
            resp = client.post(
                "/v1/messages/count_tokens",
                json={
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "hi"}],
                },
                headers={"x-api-key": "test"},
            )
            assert resp.status_code in (404, 405), (
                f"Expected 404/405 when Anthropic compat disabled, got {resp.status_code}"
            )
        finally:
            restore()


class TestResponsesApiDisabled:
    """When ENABLE_RESPONSES_API is false, /v1/responses is not registered."""

    def test_responses_returns_404(self):
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="true", responses_api="false"
        )
        try:
            resp = client.post(
                "/v1/responses",
                json={"model": "test-model", "input": "hello"},
                headers={"authorization": "Bearer test"},
            )
            assert resp.status_code in (404, 405), (
                f"Expected 404/405 when Responses API disabled, got {resp.status_code}"
            )
        finally:
            restore()


class TestBothDisabled:
    """When both compat layers are disabled, core endpoints still work."""

    @patch("mapper.list_downstream", new_callable=AsyncMock)
    @patch("mapper.workflow_models", return_value=[])
    def test_chat_completions_still_works(self, _wf, mock_downstream):
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            # Patch mapper on the freshly loaded main module
            main_mod.mapper.list_downstream = mock_downstream
            mock_downstream.return_value = []

            # /v1/chat/completions is always registered (though it will fail
            # at the mapper level without a model — we just check it's not 404)
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
                headers={"authorization": "Bearer test"},
            )
            # Should not be 404 (route exists) — will be 400/500 due to no
            # backend, but that proves the route is registered
            assert resp.status_code != 404, "chat/completions should be registered"
        finally:
            restore()

    @patch("mapper.list_downstream", new_callable=AsyncMock)
    @patch("mapper.workflow_models", return_value=[])
    def test_models_endpoint_still_works(self, _wf, mock_downstream):
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            main_mod.mapper.list_downstream = mock_downstream
            main_mod.mapper.workflow_models = _wf
            mock_downstream.return_value = [
                {"id": "test-model", "object": "model", "created": 0, "owned_by": "test"},
            ]
            main_mod.config.BOOST_MODS.__value__ = []
            main_mod.config.SERVE_BASE_MODELS.__value__ = True
            main_mod.config.MODEL_FILTER.__value__ = []

            resp = client.get(
                "/v1/models",
                headers={"authorization": "Bearer test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["object"] == "list"
            assert len(data["data"]) == 1
        finally:
            restore()

    def test_messages_returns_404(self):
        client, _, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            resp = client.post(
                "/v1/messages",
                json={
                    "model": "test-model",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            assert resp.status_code in (404, 405)
        finally:
            restore()

    def test_responses_returns_404(self):
        client, _, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            resp = client.post(
                "/v1/responses",
                json={"model": "test-model", "input": "hello"},
            )
            assert resp.status_code in (404, 405)
        finally:
            restore()


class TestBothEnabled:
    """When both compat layers are enabled, all endpoints are reachable."""

    @patch("mapper.list_downstream", new_callable=AsyncMock)
    @patch("mapper.workflow_models", return_value=[])
    def test_models_works(self, _wf, mock_downstream):
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="true", responses_api="true"
        )
        try:
            main_mod.mapper.list_downstream = mock_downstream
            main_mod.mapper.workflow_models = _wf
            mock_downstream.return_value = [
                {"id": "m1", "object": "model", "created": 0, "owned_by": "test"},
            ]
            main_mod.config.BOOST_MODS.__value__ = []
            main_mod.config.SERVE_BASE_MODELS.__value__ = True
            main_mod.config.MODEL_FILTER.__value__ = []

            resp = client.get("/v1/models", headers={"authorization": "Bearer test"})
            assert resp.status_code == 200
        finally:
            restore()

    def test_messages_reachable(self):
        """POST /v1/messages reaches the Anthropic handler (not 404)."""
        client, _, restore = _make_fresh_app(
            anthropic_compat="true", responses_api="true"
        )
        try:
            resp = client.post(
                "/v1/messages",
                json={
                    "model": "test-model",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            # Not 404 — the route exists. It may fail at mapper resolution
            # but the handler was invoked.
            assert resp.status_code != 404, "messages should be registered when enabled"
        finally:
            restore()

    def test_responses_reachable(self):
        """POST /v1/responses reaches the Responses handler (not 404)."""
        client, _, restore = _make_fresh_app(
            anthropic_compat="true", responses_api="true"
        )
        try:
            resp = client.post(
                "/v1/responses",
                json={"model": "test-model", "input": "hello"},
            )
            assert resp.status_code != 404, "responses should be registered when enabled"
        finally:
            restore()

    @patch("mapper.list_downstream", new_callable=AsyncMock)
    @patch("mapper.workflow_models", return_value=[])
    def test_chat_completions_works(self, _wf, mock_downstream):
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="true", responses_api="true"
        )
        try:
            main_mod.mapper.list_downstream = mock_downstream
            mock_downstream.return_value = []

            resp = client.post(
                "/v1/chat/completions",
                json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
                headers={"authorization": "Bearer test"},
            )
            assert resp.status_code != 404, "chat/completions should be registered"
        finally:
            restore()


class TestModelsEndpointIndependentOfCompat:
    """The /v1/models endpoint works regardless of compat layer config."""

    @patch("mapper.list_downstream", new_callable=AsyncMock)
    @patch("mapper.workflow_models", return_value=[])
    def test_models_with_anthropic_only(self, _wf, mock_downstream):
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="true", responses_api="false"
        )
        try:
            main_mod.mapper.list_downstream = mock_downstream
            main_mod.mapper.workflow_models = _wf
            mock_downstream.return_value = [
                {"id": "m1", "object": "model", "created": 0, "owned_by": "test"},
            ]
            main_mod.config.BOOST_MODS.__value__ = []
            main_mod.config.SERVE_BASE_MODELS.__value__ = True
            main_mod.config.MODEL_FILTER.__value__ = []

            resp = client.get("/v1/models", headers={"authorization": "Bearer test"})
            assert resp.status_code == 200
        finally:
            restore()

    @patch("mapper.list_downstream", new_callable=AsyncMock)
    @patch("mapper.workflow_models", return_value=[])
    def test_models_with_responses_only(self, _wf, mock_downstream):
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="true"
        )
        try:
            main_mod.mapper.list_downstream = mock_downstream
            main_mod.mapper.workflow_models = _wf
            mock_downstream.return_value = [
                {"id": "m1", "object": "model", "created": 0, "owned_by": "test"},
            ]
            main_mod.config.BOOST_MODS.__value__ = []
            main_mod.config.SERVE_BASE_MODELS.__value__ = True
            main_mod.config.MODEL_FILTER.__value__ = []

            resp = client.get("/v1/models", headers={"authorization": "Bearer test"})
            assert resp.status_code == 200
        finally:
            restore()

    @patch("mapper.list_downstream", new_callable=AsyncMock)
    @patch("mapper.workflow_models", return_value=[])
    def test_models_with_none(self, _wf, mock_downstream):
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            main_mod.mapper.list_downstream = mock_downstream
            main_mod.mapper.workflow_models = _wf
            mock_downstream.return_value = [
                {"id": "m1", "object": "model", "created": 0, "owned_by": "test"},
            ]
            main_mod.config.BOOST_MODS.__value__ = []
            main_mod.config.SERVE_BASE_MODELS.__value__ = True
            main_mod.config.MODEL_FILTER.__value__ = []

            resp = client.get("/v1/models", headers={"authorization": "Bearer test"})
            assert resp.status_code == 200
        finally:
            restore()

    @patch("mapper.list_downstream", new_callable=AsyncMock)
    @patch("mapper.workflow_models", return_value=[])
    def test_models_with_both(self, _wf, mock_downstream):
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="true", responses_api="true"
        )
        try:
            main_mod.mapper.list_downstream = mock_downstream
            main_mod.mapper.workflow_models = _wf
            mock_downstream.return_value = [
                {"id": "m1", "object": "model", "created": 0, "owned_by": "test"},
            ]
            main_mod.config.BOOST_MODS.__value__ = []
            main_mod.config.SERVE_BASE_MODELS.__value__ = True
            main_mod.config.MODEL_FILTER.__value__ = []

            resp = client.get("/v1/models", headers={"authorization": "Bearer test"})
            assert resp.status_code == 200
        finally:
            restore()


class TestHealthEndpointIndependentOfCompat:
    """Health and root endpoints work regardless of compat config."""

    def test_health_both_disabled(self):
        client, _, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
        finally:
            restore()

    def test_root_both_disabled(self):
        client, _, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            resp = client.get("/")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
        finally:
            restore()
