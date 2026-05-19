"""Shared test fixtures for Boost compat layer tests.

Registers module stubs for heavy dependencies (mapper, llm) that the compat
layers import but tests mock individually. All stubs carry the full set of
attributes that any test file might monkeypatch, preventing cross-test
isolation failures when pytest collects multiple test files in one session.
"""

import os
import sys
import types

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
os.chdir(SRC_DIR)

# Stub mapper and llm before any compat module is imported.
# Both test files need these attributes for monkeypatch.setattr().
for mod_name in ("mapper", "llm"):
    stub = sys.modules.get(mod_name)
    if stub is None or not hasattr(stub, "__stub__"):
        stub = types.ModuleType(mod_name)
        stub.__stub__ = True
        sys.modules[mod_name] = stub

    if mod_name == "mapper":
        if not hasattr(stub, "list_downstream"):
            stub.list_downstream = None
        if not hasattr(stub, "resolve_request_config"):
            stub.resolve_request_config = None
        if not hasattr(stub, "is_direct_task"):
            stub.is_direct_task = None

    if mod_name == "llm":
        if not hasattr(stub, "LLM"):
            stub.LLM = None
