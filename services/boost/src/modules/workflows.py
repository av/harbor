"""Built-in workflow presets for agentic coding modules."""

from copy import deepcopy

TOOLS_SETUP = {"module": "tools", "config": {"final": False}}
FINAL_STEP = "final"

PRESETS: dict[str, dict] = {
  "research-quick": {
    "name": "Quick Research",
    "description": "Register portable tools, run fast caveman web research, then answer.",
    "modules": [TOOLS_SETUP, "caveman", FINAL_STEP],
  },
  "research-deep": {
    "name": "Deep Research",
    "description": "Register portable tools, run two-hop ponytail research, then answer.",
    "modules": [TOOLS_SETUP, "ponytail", FINAL_STEP],
  },
  "code-check": {
    "name": "Code Check",
    "description": "Register portable tools, audit coding deliverables with autocheck, then answer.",
    "modules": [TOOLS_SETUP, "autocheck", FINAL_STEP],
  },
  "agent-research": {
    "name": "Agent Research",
    "description": "Tool-enabled smash-and-grab research for agentic coding sessions.",
    "modules": [TOOLS_SETUP, "caveman", FINAL_STEP],
  },
  "shipyard": {
    "name": "Shipyard",
    "description": (
      "Full agentic coding pipeline: keel grounding, selective caveman ideation, "
      "portable tools, ponytail implementation research, and autocheck audit."
    ),
    "modules": [
      {"module": "keel", "continue": True, "config": {"defer_final": True}},
      {"module": "caveman", "continue": True, "config": {"defer_final": True}},
      TOOLS_SETUP,
      {"module": "ponytail", "continue": True, "config": {"defer_final": True}},
      "autocheck",
      FINAL_STEP,
    ],
  },
}


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