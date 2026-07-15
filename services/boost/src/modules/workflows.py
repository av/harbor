"""Workflow preset helpers for agentic coding modules."""

from copy import deepcopy

TOOLS_SETUP = {"module": "tools", "config": {"final": False}}
FINAL_STEP = "final"

PRESETS: dict[str, dict] = {}


def _module_name(module_config) -> str | None:
  if isinstance(module_config, str):
    return module_config
  if isinstance(module_config, dict):
    return module_config.get("module") or module_config.get("handle")
  return None


def shorthand_for(modules: list) -> str:
  """Build env/@boost_workflow shorthand from a preset module chain."""
  names = []
  for module_config in modules:
    name = _module_name(module_config)
    if name:
      names.append(name)
  return ",".join(names)


# Shorthand form used in HARBOR_BOOST_WORKFLOWS and @boost_workflow metadata.
SHORTHAND: dict[str, str] = {
  workflow_id: shorthand_for(preset["modules"])
  for workflow_id, preset in PRESETS.items()
}


def definitions() -> dict[str, dict]:
  return deepcopy(PRESETS)
