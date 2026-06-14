"""Unit tests for built-in agentic coding workflow presets."""

import os
import sys
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import mods
import workflows
from modules import workflows as workflow_presets


SIMPLE_PRESETS = {
  "research-quick": ("caveman", "Quick Research"),
  "research-deep": ("ponytail", "Deep Research"),
  "code-check": ("autocheck", "Code Check"),
  "agent-research": ("caveman", "Agent Research"),
}

SHIPYARD_MODULES = [
  {"module": "keel", "continue": True, "config": {"defer_final": True}},
  {"module": "caveman", "continue": True, "config": {"defer_final": True}},
  {"module": "tools", "config": {"final": False}},
  {"module": "ponytail", "continue": True, "config": {"defer_final": True}},
  "autocheck",
  "final",
]


@pytest.fixture(autouse=True)
def reset_workflow_registry():
  workflows.invalidate_registry()
  yield
  workflows.invalidate_registry()


class TestWorkflowPresets:
  def test_presets_include_all_agentic_workflows(self):
    assert set(workflow_presets.PRESETS) == set(SIMPLE_PRESETS) | {"shipyard"}

  @pytest.mark.parametrize(
    "workflow_id,module_name",
    [(workflow_id, module_name) for workflow_id, (module_name, _name) in SIMPLE_PRESETS.items()],
  )
  def test_preset_module_chain(self, workflow_id, module_name):
    preset = workflow_presets.PRESETS[workflow_id]
    modules = preset["modules"]

    assert modules[0] == {"module": "tools", "config": {"final": False}}
    assert modules[1] == module_name
    assert modules[2] == "final"

  def test_shipyard_preset_module_chain(self):
    preset = workflow_presets.PRESETS["shipyard"]
    assert preset["name"] == "Shipyard"
    assert preset["modules"] == SHIPYARD_MODULES

  def test_shipyard_shorthand_matches_module_chain(self):
    shorthand = workflow_presets.SHORTHAND["shipyard"]
    assert shorthand == "keel,caveman,tools,ponytail,autocheck,final"

  @pytest.mark.parametrize(
    "workflow_id,module_name",
    [(workflow_id, module_name) for workflow_id, (module_name, _name) in SIMPLE_PRESETS.items()],
  )
  def test_shorthand_matches_module_chain(self, workflow_id, module_name):
    shorthand = workflow_presets.SHORTHAND[workflow_id]
    assert shorthand == f"tools,{module_name},final"

  def test_definitions_returns_copy_of_presets(self):
    loaded = workflow_presets.definitions()
    assert loaded == workflow_presets.PRESETS
    loaded["research-quick"]["name"] = "changed"
    assert workflow_presets.PRESETS["research-quick"]["name"] == "Quick Research"

  def test_preset_ids_do_not_collide_with_module_prefixes(self):
    for workflow_id in workflow_presets.PRESETS:
      assert workflow_id not in mods.registry

  @pytest.mark.parametrize("workflow_id", list(SIMPLE_PRESETS) + ["shipyard"])
  def test_normalize_workflow_accepts_preset(self, workflow_id):
    normalized = workflows.normalize_workflow(workflow_presets.PRESETS[workflow_id], workflow_id)
    assert normalized is not None
    assert normalized["id"] == workflow_id

  def test_load_workflows_includes_builtin_presets(self, monkeypatch):
    monkeypatch.setattr(config.WORKFLOWS, "__value__", "")
    monkeypatch.setattr(workflows, "_load_file_definitions", lambda: [])
    loaded = workflows.load_workflows()
    for workflow_id in SIMPLE_PRESETS:
      assert workflow_id in loaded
    assert "shipyard" in loaded

  def test_env_workflow_overrides_builtin_preset(self, monkeypatch):
    monkeypatch.setattr(config.WORKFLOWS, "__value__", "research-quick=tools,g1,final")
    monkeypatch.setattr(workflows, "_load_file_definitions", lambda: [])
    loaded = workflows.load_workflows()
    assert loaded["research-quick"]["modules"] == ["tools", "g1", "final"]

  def test_split_workflow_model_recognizes_preset_prefix(self, monkeypatch):
    monkeypatch.setattr(config.WORKFLOWS, "__value__", "")
    monkeypatch.setattr(workflows, "_load_file_definitions", lambda: [])
    workflows.invalidate_registry()

    workflow, base_model = workflows.split_workflow_model("research-deep-llama3.2")
    assert workflow is not None
    assert workflow["id"] == "research-deep"
    assert base_model == "llama3.2"

  def test_model_for_prefixes_base_model_id(self):
    workflow = workflows.normalize_workflow(workflow_presets.PRESETS["code-check"], "code-check")
    model = workflows.model_for(workflow, {"id": "gpt-4o", "name": "GPT-4o"})
    assert model["id"] == "code-check-gpt-4o"
    assert model["owned_by"] == "harbor-boost-workflow"
    assert model["boost_workflow"]["id"] == "code-check"

  def test_shorthand_parser_round_trip(self):
    for workflow_id, shorthand in workflow_presets.SHORTHAND.items():
      parsed = workflows.normalize_workflow(f"{workflow_id}={shorthand}")
      assert parsed is not None
      assert parsed["id"] == workflow_id
      assert parsed["modules"] == [name for name in shorthand.split(",")]


class TestApplyWorkflow:
  @pytest.mark.asyncio
  async def test_tools_setup_does_not_stream_before_research_module(self):
    chat = MagicMock()
    llm = MagicMock()
    llm.is_final_stream = False
    llm.stream_final_completion = AsyncMock()

    with patch.object(workflows, "_apply_module", new_callable=AsyncMock) as mock_apply:
      await workflows.apply_workflow(deepcopy(workflow_presets.PRESETS["research-quick"]), chat, llm)

    tools_call = mock_apply.await_args_list[0]
    assert tools_call.args[0] == "tools"
    assert tools_call.args[1]["final"] is False
    assert mock_apply.await_args_list[1].args[0] == "caveman"
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_shipyard_runs_full_module_chain_before_final(self):
    chat = MagicMock()
    llm = MagicMock()
    llm.is_final_stream = False
    llm.stream_final_completion = AsyncMock()

    with patch.object(workflows, "_apply_module", new_callable=AsyncMock) as mock_apply:
      await workflows.apply_workflow(deepcopy(workflow_presets.PRESETS["shipyard"]), chat, llm)

    applied = [call.args[0] for call in mock_apply.await_args_list]
    assert applied == ["keel", "caveman", "tools", "ponytail", "autocheck"]
    assert mock_apply.await_args_list[0].args[1]["defer_final"] is True
    assert mock_apply.await_args_list[2].args[1]["final"] is False
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_workflow_streams_final_when_last_step_missing(self):
    chat = MagicMock()
    llm = MagicMock()
    llm.is_final_stream = False
    llm.stream_final_completion = AsyncMock()

    definition = {
      "id": "research-quick",
      "modules": [{"module": "tools", "config": {"final": False}}, "caveman"],
    }

    with patch.object(workflows, "_apply_module", new_callable=AsyncMock):
      await workflows.apply_workflow(definition, chat, llm)

    llm.stream_final_completion.assert_awaited_once()