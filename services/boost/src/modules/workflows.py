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
}

# Shorthand form used in HARBOR_BOOST_WORKFLOWS and @boost_workflow metadata.
SHORTHAND: dict[str, str] = {
  workflow_id: "tools,caveman,final"
  if workflow_id in {"research-quick", "agent-research"}
  else "tools,ponytail,final"
  if workflow_id == "research-deep"
  else "tools,autocheck,final"
  for workflow_id in PRESETS
}


def definitions() -> dict[str, dict]:
  return deepcopy(PRESETS)