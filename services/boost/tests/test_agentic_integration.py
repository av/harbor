"""Integration tests for agentic Boost modules and workflow presets."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import mods
import workflows
from modules import workflows as workflow_presets


AGENTIC_MODULES = {
  "caveman": "caveman",
  "ponytail": "ponytail",
  "autocheck": "autocheck",
  "keel": "keel",
  "sightline": "sightline",
}

EXPECTED_PRESET_IDS = {
  "research-quick",
  "research-deep",
  "code-check",
  "scope-guard",
  "agent-research",
  "agent-code",
  "shipyard",
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


class TestAgenticWorkflowPresets:
  def test_builtin_presets_include_shipyard(self):
    assert set(workflow_presets.PRESETS) == EXPECTED_PRESET_IDS

  @pytest.mark.parametrize("workflow_id", sorted(EXPECTED_PRESET_IDS))
  def test_workflow_presets_resolve_correctly(self, workflow_id, monkeypatch):
    monkeypatch.setattr(config.WORKFLOWS, "__value__", "")
    monkeypatch.setattr(workflows, "_load_file_definitions", lambda: [])

    loaded = workflows.load_workflows()
    assert workflow_id in loaded

    workflow = workflows.get(workflow_id)
    assert workflow is not None
    assert workflow["id"] == workflow_id
    assert workflow["name"] == workflow_presets.PRESETS[workflow_id]["name"]
    assert workflow["modules"] == workflow_presets.PRESETS[workflow_id]["modules"]

  def test_shipyard_preset_references_registered_modules(self, monkeypatch):
    monkeypatch.setattr(config.WORKFLOWS, "__value__", "")
    monkeypatch.setattr(workflows, "_load_file_definitions", lambda: [])

    workflow = workflows.get("shipyard")
    module_names = []
    for module_config in workflow["modules"]:
      if isinstance(module_config, str):
        module_names.append(module_config)
      elif isinstance(module_config, dict):
        module_names.append(module_config["module"])

    for module_name in module_names:
      if module_name == "final":
        continue
      assert module_name in mods.registry

  def test_workflow_ids_do_not_collide_with_module_prefixes(self):
    for workflow_id in EXPECTED_PRESET_IDS:
      assert workflow_id not in mods.registry