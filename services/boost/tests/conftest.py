"""Shared test fixtures for Boost tests.

Stubs the ``mapper`` module, whose real implementation has heavy dependencies
(asyncache) that are not available in the test environment.  The ``llm``
module is left alone — it imports successfully from *src/* and is needed by
both the compat-layer tests (which mock it per-test) and ``test_streaming.py``
(which exercises the real ``LLM`` class).
"""

import os
import sys
import types

import pytest

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
os.chdir(SRC_DIR)

# Stub only mapper — it cannot be imported in the test environment due to
# missing asyncache.  The compat test files monkeypatch these attributes
# per-test with real mocks.
_mapper_stub = sys.modules.get("mapper")
if _mapper_stub is None or not hasattr(_mapper_stub, "__stub__"):
    _mapper_stub = types.ModuleType("mapper")
    _mapper_stub.__stub__ = True
    sys.modules["mapper"] = _mapper_stub

for _attr in ("list_downstream", "resolve_request_config", "is_direct_task",
              "get_proxy_model", "workflow_models"):
    if not hasattr(_mapper_stub, _attr):
        setattr(_mapper_stub, _attr, None)


@pytest.fixture(autouse=True)
def _restore_mapper_stub():
    """Undo per-test swaps of the ``mapper`` module.

    Some coverage tests replace ``sys.modules['mapper']`` with the real module
    and rebind the module-level ``mapper`` name inside ``main``,
    ``anthropic_compat``, and ``responses_compat``.  Without restoration,
    later tests monkeypatch the wrong module object (their FakeLLM/mapper
    mocks never take effect) and fail with backend 500s.  Snapshot the
    bindings before each test and put them back afterwards.
    """
    saved_sys = sys.modules.get("mapper")
    holders = ("main", "anthropic_compat", "responses_compat")
    saved_refs = {
        name: sys.modules[name].mapper
        for name in holders
        if name in sys.modules and hasattr(sys.modules[name], "mapper")
    }
    llm_mod = sys.modules.get("llm")
    saved_llm_cls = getattr(llm_mod, "LLM", None)
    # Tests also mutate config values in place (cfg.__value__ = ...) without
    # restoring; snapshot the ones known to leak across tests.
    config_mod = sys.modules.get("config")
    config_keys = ("BOOST_MODS", "SERVE_BASE_MODELS", "MODEL_FILTER",
                   "BOOST_APIS", "BOOST_KEYS", "BOOST_AUTH")
    saved_cfg = {}
    if config_mod is not None:
        for key in config_keys:
            cfg = getattr(config_mod, key, None)
            if cfg is not None and hasattr(cfg, "__value__"):
                saved_cfg[key] = cfg.__value__
    mods_mod = sys.modules.get("mods")
    saved_registry = getattr(mods_mod, "registry", None)
    yield
    if mods_mod is not None and saved_registry is not None \
            and sys.modules.get("mods") is mods_mod:
        mods_mod.registry = saved_registry
    if saved_sys is not None:
        sys.modules["mapper"] = saved_sys
    for name, ref in saved_refs.items():
        mod = sys.modules.get(name)
        if mod is not None:
            mod.mapper = ref
    if llm_mod is not None and saved_llm_cls is not None:
        current = sys.modules.get("llm")
        if current is llm_mod:
            llm_mod.LLM = saved_llm_cls
    if config_mod is not None and sys.modules.get("config") is config_mod:
        for key, value in saved_cfg.items():
            cfg = getattr(config_mod, key, None)
            if cfg is not None:
                cfg.__value__ = value
