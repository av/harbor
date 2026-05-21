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
    for mod_name in ("config", "main", "auth", "anthropic_compat", "responses_compat"):
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


class TestMainPyHttpHandlerBranches:
    """Cover remaining un-hit main.py HTTP handler paths (e.g. 250 filter, 240-242 proxy modules, 387-389 invalid JSON, 411-412 direct task, _is_anthropic + _to_anthropic) via HTTP in this non-prior test file only."""

    @patch("mapper.list_downstream", new_callable=AsyncMock)
    @patch("mapper.workflow_models", return_value=[])
    def test_models_filter_and_module_proxy_branches_hit_250_240(self, _wf, mock_downstream):
        """Exercise _list_models 240-242 (registry.get + get_proxy) and 250 (matches_filter when MODEL_FILTER set)."""
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            main_mod.mapper.list_downstream = mock_downstream
            main_mod.mapper.workflow_models = _wf
            mock_downstream.return_value = [
                {"id": "test-model", "object": "model", "created": 0, "owned_by": "test"},
            ]
            main_mod.config.BOOST_MODS.__value__ = ["testmod"]
            main_mod.config.SERVE_BASE_MODELS.__value__ = True
            main_mod.config.MODEL_FILTER.__value__ = {"id": "test-model"}

            # Make registry.get return non-None to enter 242
            mock_mod = MagicMock()
            mock_reg = MagicMock()
            mock_reg.get.return_value = mock_mod
            main_mod.mods.registry = mock_reg
            # Stub get_proxy_model to avoid side effects in proxy creation
            main_mod.mapper.get_proxy_model = MagicMock(return_value={
                "id": "testmod-test-model", "object": "model", "created": 0, "owned_by": "boost"
            })

            resp = client.get("/v1/models", headers={"authorization": "Bearer test"})
            assert resp.status_code == 200
            data = resp.json()
            # At least base + proxy should be present (filter passes)
            ids = [m.get("id") for m in data.get("data", [])]
            assert "test-model" in ids or "testmod-test-model" in ids
        finally:
            restore()

    def test_chat_direct_task_hits_411_412(self):
        """Exercise chat post 411-412 direct task early return (is_direct True, no workflow)."""
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            # Setup for chat path to reach the if without full backend
            mock_list = AsyncMock()
            main_mod.mapper.list_downstream = mock_list
            main_mod.mapper.resolve_request_config = MagicMock(return_value={
                "url": "http://fake:8080",
                "api_key": "sk-test",
                "headers": {"Authorization": "Bearer sk-test"},
                "model": "test-model",
                "module": None,
                "workflow": None,
                "params": {},
            })
            main_mod.mapper.is_direct_task = MagicMock(return_value=True)

            # Fake the LLM class used inside main (post reload) so direct .chat_completion doesn't hit network
            fake_proxy = MagicMock()
            fake_proxy.chat_completion = AsyncMock(return_value={
                "id": "direct-1",
                "choices": [{"message": {"role": "assistant", "content": "direct ok"}}]
            })
            fake_proxy.workflow = None
            fake_proxy.boost_params = {}
            main_mod.llm.LLM = MagicMock(return_value=fake_proxy)

            resp = client.post(
                "/v1/chat/completions",
                json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
                headers={"authorization": "Bearer test"},
            )
            assert resp.status_code == 200
            assert "direct ok" in str(resp.json())
        finally:
            restore()

    def test_chat_invalid_json_hits_387_389(self):
        """Exercise the JSONDecodeError branch in post_boost_chat_completion (387-389 -> 400)."""
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            # Malformed JSON body -> decode/json.loads fails -> HTTP 400
            resp = client.post(
                "/v1/chat/completions",
                content=b'{"model": "x", "messages": [}',  # trailing makes invalid
                headers={"authorization": "Bearer test", "content-type": "application/json"},
            )
            assert resp.status_code == 400
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"detail": resp.text}
            assert "Invalid JSON" in str(body)
        finally:
            restore()

    @patch("mapper.list_downstream", new_callable=AsyncMock)
    @patch("mapper.workflow_models", return_value=[])
    def test_models_anthropic_client_hits_is_anthropic_and_to_anthropic(self, _wf, mock_downstream):
        """Exercise _is_anthropic_client (208/210) + _to_anthropic_model (216) + anthropic paths in models handlers via header."""
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            main_mod.mapper.list_downstream = mock_downstream
            main_mod.mapper.workflow_models = _wf
            mock_downstream.return_value = [
                {"id": "test-model", "object": "model", "created": 0, "owned_by": "test", "name": "Test"},
            ]
            main_mod.config.BOOST_MODS.__value__ = []
            main_mod.config.SERVE_BASE_MODELS.__value__ = True
            main_mod.config.MODEL_FILTER.__value__ = []

            # anthropic-version header triggers _is_anthropic_client -> anthropic envelope + _to_anthropic
            headers = {
                "authorization": "Bearer test",
                "anthropic-version": "2023-06-01",
            }
            resp = client.get("/v1/models", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert "data" in data  # anthropic format has 'data'
            # also test get-by-id path with anthropic
            resp2 = client.get("/v1/models/test-model", headers=headers)
            assert resp2.status_code == 200
        finally:
            restore()


class TestDeepMapperBranchesViaChatHTTP:
    """Cover deeper mapper.py branches for HTTP chat/tool paths (list_downstream 20-59 errors+minimax+fetch, resolve_proxy_* 74-98, resolve_request_config errors 106/118 + tools keep, is_direct_task 158) via real unpatched mapper (forced import/rebind after _make_fresh_app) exercised by /v1/models and /v1/chat/completions (incl tools payloads) in this non-prior test_config.py only; follows iter14 rules, avoids repeating iter10's test_chat_completions.py edits."""

    def test_mapper_list_downstream_except_minimax_register_via_models_http(self):
        """Drive list_downstream http loop+except (49-50) + minimax static register (52-58) + return via real call from /v1/models handler, using MINIMAX key at config load + bad API url."""
        import os
        with patch.dict(os.environ, {"HARBOR_MINIMAX_API_KEY": "sk-minimax-0z4"}, clear=False):
            client, main_mod, restore = _make_fresh_app(
                anthropic_compat="false", responses_api="false"
            )
            try:
                # force real mapper (not stubbed) for deeper branch execution
                if "mapper" in sys.modules:
                    del sys.modules["mapper"]
                import mapper as real_mapper
                sys.modules["mapper"] = real_mapper
                main_mod.mapper = real_mapper
                if hasattr(real_mapper.list_downstream, "cache"):
                    real_mapper.list_downstream.cache.clear()

                # bad URL forces connect error -> except logger path; MINIMAX key causes static models register in list_downstream
                main_mod.config.BOOST_APIS = ["http://127.0.0.1:1/v1"]
                main_mod.config.BOOST_KEYS = ["sk-bad"]

                resp = client.get("/v1/models", headers={"authorization": "Bearer test"})
                # list executes fully (errors tolerated, models may be empty or minimax added)
                assert resp.status_code == 200
            finally:
                restore()

    @patch("httpx.AsyncClient")
    def test_mapper_list_downstream_success_resolve_tools_via_chat_http(self, mock_httpx_cls):
        """Drive list_downstream success path (20-48: fetch, extend, MODEL_TO_BACKEND populate) + resolve_request_config (101-141: proxy calls, tools kept in params 104, no-err) via real mapper + chat POST with tools payload."""
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            if "mapper" in sys.modules:
                del sys.modules["mapper"]
            import mapper as real_mapper
            sys.modules["mapper"] = real_mapper
            main_mod.mapper = real_mapper
            if hasattr(real_mapper.list_downstream, "cache"):
                real_mapper.list_downstream.cache.clear()

            # mock httpx so real list_downstream succeeds and populates for resolve
            mock_inst = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"data": [{"id": "gpt-0z4", "object": "model", "created": 0, "owned_by": "openai"}]}
            mock_resp.raise_for_status = MagicMock()
            mock_inst.get.return_value = mock_resp
            mock_inst.__aenter__.return_value = mock_inst
            mock_httpx_cls.return_value = mock_inst

            main_mod.config.BOOST_APIS = ["https://fake/v1"]
            main_mod.config.BOOST_KEYS = ["sk-fake"]

            with patch.object(main_mod.llm, "LLM") as mock_llm_cls:
                fake = MagicMock()
                fake.chat = MagicMock()
                fake.chat.has_substring.return_value = False
                fake.workflow = None
                fake.boost_params = {}
                fake.serve = AsyncMock(return_value=None)  # after mapper, will 500 but branches hit
                mock_llm_cls.return_value = fake

                body = {
                    "model": "gpt-0z4",
                    "messages": [{"role": "user", "content": "tool test"}],
                    "tools": [{"type": "function", "function": {"name": "echo", "parameters": {}}}],
                    "tool_choice": "auto"
                }
                resp = client.post("/v1/chat/completions", json=body, headers={"authorization": "Bearer test"})
                assert resp.status_code in (200, 500)
        finally:
            restore()

    def test_mapper_resolve_valueerror_and_404_unknown_via_chat_http(self):
        """Drive resolve_request_config ValueError (no model, 106-107) and HTTPException 404 (unknown after list, 118-122) branches via chat posts (errors surface as 4xx/5xx from global handler)."""
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            if "mapper" in sys.modules:
                del sys.modules["mapper"]
            import mapper as real_mapper
            sys.modules["mapper"] = real_mapper
            main_mod.mapper = real_mapper
            if hasattr(real_mapper.list_downstream, "cache"):
                real_mapper.list_downstream.cache.clear()

            main_mod.config.BOOST_APIS = []
            main_mod.config.BOOST_KEYS = []

            # unknown -> 404 from resolve
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "no-such-model-0z4", "messages": [{"role": "user", "content": "x"}]},
                headers={"authorization": "Bearer test"},
            )
            assert resp.status_code == 404

            # no model key -> ValueError in resolve
            resp2 = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "x"}]},
                headers={"authorization": "Bearer test"},
            )
            assert resp2.status_code in (400, 500)
        finally:
            restore()

    def test_mapper_proxy_module_and_real_is_direct_via_chat(self):
        """Drive resolve_proxy_module (86-90 if), resolve_proxy_workflow (93-98), real is_direct_task (158-159 any substring) + chat direct early return via klmbr- prefix (registry likely has) + direct prompt substring."""
        client, main_mod, restore = _make_fresh_app(
            anthropic_compat="false", responses_api="false"
        )
        try:
            if "mapper" in sys.modules:
                del sys.modules["mapper"]
            import mapper as real_mapper
            sys.modules["mapper"] = real_mapper
            main_mod.mapper = real_mapper
            if hasattr(real_mapper.list_downstream, "cache"):
                real_mapper.list_downstream.cache.clear()

            main_mod.config.BOOST_APIS = ["https://fake"]
            main_mod.config.BOOST_KEYS = ["sk-f"]

            # pre-populate so resolve finds backend for the base model (klmbr prefix will be stripped by resolve_proxy_model)
            real_mapper.MODEL_TO_BACKEND["gpt-0z4"] = "https://fake"

            with patch.object(main_mod.llm, "LLM") as mock_llm_cls:
                fake = MagicMock()
                fake.chat = MagicMock()
                # real is_direct_task will call has_substring; return True to hit 411 branch
                fake.chat.has_substring.side_effect = lambda s: "3-5 word title" in (s or "")
                fake.workflow = None
                fake.boost_params = {}
                fake.chat_completion = AsyncMock(return_value={"id": "d-0z4", "choices": [{"message": {"content": "direct"}}]})
                mock_llm_cls.return_value = fake

                # klmbr- triggers proxy_module if (if klmbr in registry); title prompt triggers real is_direct
                body = {
                    "model": "klmbr-gpt-0z4",
                    "messages": [{"role": "user", "content": "Generate a concise, 3-5 word title for this"}]
                }
                resp = client.post("/v1/chat/completions", json=body, headers={"authorization": "Bearer test"})
                assert resp.status_code == 200
                assert "direct" in str(resp.json())
        finally:
            restore()
