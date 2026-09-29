import inspect

import codemode_sandbox
import config
import log
import research.workflow as workflow_mod
import tools.registry
from modules import tools as tools_mod
from tools.registry import LOCAL_TOOL_PREFIX

ID_PREFIX = 'codemode'

DOCS = """
Replaces the whole local tool catalog with a single `execute_code` tool. Instead
of one tool call per action, the model writes one Python program that calls the
other tools as plain functions; Boost runs the program in a subprocess and
round-trips every function call back to the real tool.

The module registers the same tools as the `tools` module (`HARBOR_BOOST_TOOLS`,
plus workspace tools when `HARBOR_BOOST_WORKSPACE_ROOT` is set) and absorbs any
tools an earlier workflow step registered. All of them are then hidden from the
downstream LLM: it only ever sees `execute_code(code)`. Their signatures and
docstring summaries are rendered into a system message so the model knows what
it may call. Hidden tools stay in the local registry, so a model that ignores
the prompt and calls one by name is still served by Boost instead of having the
call passed back to the API client.

Output comes back from `print(...)` and from a variable named `result`. Programs
are capped by `HARBOR_BOOST_CODEMODE_TIMEOUT` seconds,
`HARBOR_BOOST_CODEMODE_MAX_OUTPUT` characters of output and
`HARBOR_BOOST_CODEMODE_MAX_CALLS` tool calls. Failures (timeout, traceback, call
limit) are returned to the model as text rather than raised.

The subprocess is isolated with `python -I -S`, but it shares Boost's filesystem
and network. This is process isolation, not a security sandbox: do not expose
it to untrusted prompts on a host you care about.

Client-supplied tools in the request body are left untouched and are not visible
inside the program.

```bash
harbor boost modules add codemode
harbor config set HARBOR_BOOST_TOOLS "web_search;read_url;current_time"
harbor launch --codemode --backend ollama codex
```

**Standalone**

```bash
docker run \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \\
  -e "HARBOR_BOOST_MODULES=codemode" \\
  -e "HARBOR_BOOST_SEARXNG_URL=http://host.docker.internal:33811" \\
  -p 8004:8000 \\
  ghcr.io/av/harbor-boost:latest
```
"""

logger = log.setup_logger(ID_PREFIX)

JSON_TO_PYTHON = {
  "string": "str",
  "integer": "int",
  "number": "float",
  "boolean": "bool",
  "array": "list",
  "object": "dict",
  "null": "None",
}

RULES = """
Rules:
- You have exactly one tool, `execute_code(code)`. Call it with one complete
  Python program. Call the functions above directly, they are already defined -
  do not import them and do not define them yourself.
- Get output back with `print(...)` or by assigning to a variable named
  `result`. Only printed output and `result` come back to you, nothing else.
- Prefer a single program that does all of the work over several calls.
- The functions above are not tools. `execute_code` is the only tool you can
  call; the functions only exist inside the Python program you pass to it.
""".strip()


async def execute_code(code: str) -> str:
  """
  Run a Python program that may call the functions listed in the system message.
  Printed output and a variable named `result` are returned; nothing else is.

  Args:
    code (str): Complete Python program to execute.
  """
  outcome = await codemode_sandbox.run(
    code,
    tools.registry.get_hidden_tools(),
    timeout=config.CODEMODE_TIMEOUT.value,
    max_output=config.CODEMODE_MAX_OUTPUT.value,
    max_calls=config.CODEMODE_MAX_CALLS.value,
  )
  return format_outcome(outcome)


def format_outcome(outcome: dict) -> str:
  parts = []

  stdout = (outcome.get("stdout") or "").rstrip()
  if stdout:
    parts.append(stdout)

  result = outcome.get("result")
  if result is not None:
    rendered = result if isinstance(result, str) else repr(result)
    parts.append(
      "result: " +
      codemode_sandbox.truncate(
        rendered,
        codemode_sandbox.effective_max_output(config.CODEMODE_MAX_OUTPUT.value),
      )
    )

  error = outcome.get("error")
  if error:
    parts.append("error: " + error.rstrip())

  return "\n".join(parts) if parts else "(no output)"


def python_type(schema: dict) -> str:
  if "anyOf" in schema:
    rendered = [python_type(option) for option in schema["anyOf"]]
    optional = "None" in rendered
    concrete = [name for name in rendered if name != "None"]
    if not concrete:
      return "None"
    return " | ".join(concrete + (["None"] if optional else []))

  return JSON_TO_PYTHON.get(schema.get("type"), "str")


def render_signature(name: str, parameters: dict) -> str:
  properties = parameters.get("properties") or {}
  required = set(parameters.get("required") or [])

  args = []
  for arg_name, schema in properties.items():
    rendered = f"{arg_name}: {python_type(schema)}"
    if arg_name not in required:
      default = schema.get("default", None)
      rendered += f" = {default!r}"
    args.append(rendered)

  return f"{name}({', '.join(args)}) -> str"


def render_summary(description: str | None) -> str:
  lines = []
  for line in inspect.cleandoc(description or "").splitlines():
    if line.strip().startswith("Args:"):
      break
    if not line.strip() and lines:
      break
    if line.strip():
      lines.append(line.strip())

  return "\n".join(f"    {line}" for line in lines)


def render_prompt(hidden_tools: dict) -> str:
  blocks = []
  for key in sorted(hidden_tools):
    name = key[len(LOCAL_TOOL_PREFIX):]
    definition = tools.registry.tool_def_from_fn(hidden_tools[key])["function"]
    block = render_signature(name, definition.get("parameters") or {})
    summary = render_summary(definition.get("description"))
    if summary:
      block += "\n" + summary
    blocks.append(block)

  header = (
    "You write Python to get things done. The following functions are already "
    "defined and available inside `execute_code`:"
  ) if blocks else (
    "You write Python to get things done. No helper functions are available in "
    "this request."
  )

  return "\n\n".join([header, *blocks, RULES])


def catalog(cfg: dict) -> dict:
  """Register the configured tools plus `execute_code` and return the registry."""
  for name, tool in tools_mod._selected_tools(cfg.get("tools")).items():
    try:
      tools.registry.set_local_tool(name, tool)
    except ValueError:
      logger.debug(f"Tool '{name}' already registered, skipping")

  try:
    tools.registry.set_local_tool("execute_code", execute_code)
  except ValueError:
    logger.debug("Tool 'execute_code' already registered, skipping")

  return tools.registry.get_local_tools()


def hide(local_tools: dict) -> dict:
  """Stop advertising every tool except `execute_code`, keep them callable."""
  keep = tools.registry.resolve_local_tool_name("execute_code")

  for key in list(local_tools):
    if key == keep:
      continue
    tools.registry.hide_local_tool(key)

  return tools.registry.get_hidden_tools()


def restore(hidden: dict) -> None:
  """Advertise the hidden tools again and stop advertising `execute_code`."""
  for key in list(hidden):
    tools.registry.unhide_local_tool(key)

  local_tools = tools.registry.get_local_tools()
  local_tools.pop(tools.registry.resolve_local_tool_name("execute_code"), None)


async def apply(chat, llm, config: dict | None = None):
  cfg = config or {}
  cfg_final = cfg.get("final", True)

  hidden = hide(catalog(cfg))

  try:
    chat.system(render_prompt(hidden))

    if cfg_final:
      await workflow_mod.complete_or_defer(llm, cfg)
  finally:
    # A deferred final runs after `apply` returns and must still see only
    # `execute_code`; both stores are request-scoped, so nothing outlives it.
    if not cfg.get("defer_final"):
      restore(hidden)
