"""Integration tests for agentic Boost modules."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mods
import workflows


AGENTIC_MODULES = {
  "quickhop": "quickhop",
  "deephop": "deephop",
  "caveman": "caveman",
  "ponytail": "ponytail",
  "autocheck": "autocheck",
}


@pytest.fixture(autouse=True)
def reset_workflow_registry():
  workflows.invalidate_registry()
  yield
  workflows.invalidate_registry()


class TestAgenticModuleRegistration:
  @pytest.mark.parametrize("module_name,id_prefix", list(AGENTIC_MODULES.items()))
  def test_agentic_modules_auto_register_via_mods(self, module_name, id_prefix):
    assert module_name in mods.registry
    assert mods.registry[module_name].ID_PREFIX == id_prefix

  def test_agentic_module_id_prefixes_are_unique(self):
    prefixes = [
      module.ID_PREFIX
      for module in mods.registry.values()
      if hasattr(module, "ID_PREFIX")
    ]
    assert len(prefixes) == len(set(prefixes)), (
      "Duplicate ID_PREFIX values found: "
      + ", ".join(sorted({p for p in prefixes if prefixes.count(p) > 1}))
    )
