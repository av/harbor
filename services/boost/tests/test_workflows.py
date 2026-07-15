"""Unit tests for workflow presets and the workflow engine."""

import os
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import mods
import workflows
from modules import workflows as workflow_presets

WORKFLOWS_YAML = Path(__file__).resolve().parent.parent / "src" / "workflows.yaml"


def _load_yaml_presets() -> dict[str, dict]:
  raw = yaml.safe_load(WORKFLOWS_YAML.read_text(encoding="utf-8")) or {}
  workflows_block = raw.get("workflows", raw)
  if not isinstance(workflows_block, dict):
    raise ValueError("workflows.yaml must define a workflows mapping")
  return workflows_block


def _module_names(modules: list) -> list[str]:
  names = []
  for module_config in modules:
    if isinstance(module_config, str):
      names.append(module_config)
    elif isinstance(module_config, dict):
      names.append(module_config["module"])
    else:
      raise AssertionError(f"Unexpected module config: {module_config!r}")
  return names


@pytest.fixture(autouse=True)
def reset_workflow_registry():
  workflows.invalidate_registry()
  yield
  workflows.invalidate_registry()


class TestWorkflowPresets:
  def test_no_builtin_presets(self):
    assert workflow_presets.PRESETS == {}

  def test_workflows_yaml_matches_python_presets(self):
    yaml_presets = _load_yaml_presets()
    assert set(yaml_presets) == set(workflow_presets.PRESETS)

  def test_definitions_returns_copy_of_presets(self):
    loaded = workflow_presets.definitions()
    assert loaded == workflow_presets.PRESETS

  def test_preset_ids_do_not_collide_with_module_prefixes(self):
    for workflow_id in workflow_presets.PRESETS:
      assert workflow_id not in mods.registry

  def test_shorthand_is_empty(self):
    assert workflow_presets.SHORTHAND == {}


class TestWorkflowEngine:
  def test_env_workflow_creates_custom_preset(self, monkeypatch):
    monkeypatch.setattr(config.WORKFLOWS, "__value__", "my-flow=caveman,final")
    monkeypatch.setattr(workflows, "_load_file_definitions", lambda: [])
    loaded = workflows.load_workflows()
    assert "my-flow" in loaded
    assert loaded["my-flow"]["modules"] == ["caveman", "final"]

  @pytest.mark.asyncio
  async def test_apply_workflow_streams_final_when_last_step_missing(self):
    chat = MagicMock()
    llm = MagicMock()
    llm.is_final_stream = False
    llm.stream_final_completion = AsyncMock()

    definition = {
      "id": "test-flow",
      "modules": [{"module": "tools", "config": {"final": False}}, "caveman"],
    }

    with patch.object(workflows, "_apply_module", new_callable=AsyncMock):
      await workflows.apply_workflow(definition, chat, llm)

    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_workflow_runs_modules_in_order(self):
    chat = MagicMock()
    llm = MagicMock()
    llm.is_final_stream = False
    llm.stream_final_completion = AsyncMock()

    definition = {
      "id": "test-chain",
      "modules": [
        {"module": "caveman", "continue": True, "config": {"defer_final": True}},
        {"module": "ponytail", "continue": True, "config": {"defer_final": True}},
        "final",
      ],
    }

    with patch.object(workflows, "_apply_module", new_callable=AsyncMock) as mock_apply:
      await workflows.apply_workflow(definition, chat, llm)

    applied = [call.args[0] for call in mock_apply.await_args_list]
    assert applied == ["caveman", "ponytail"]
    llm.stream_final_completion.assert_awaited_once()
