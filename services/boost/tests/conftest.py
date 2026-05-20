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

for _attr in ("list_downstream", "resolve_request_config", "is_direct_task"):
    if not hasattr(_mapper_stub, _attr):
        setattr(_mapper_stub, _attr, None)
