import inspect
from pydantic import create_model

from state import request

import log

logger = log.setup_logger(__name__)

LOCAL_TOOL_PREFIX = "__tool_"


def get_local_tools():
  request_var = request.get()
  if request_var is None:
    return {}

  local_state = request_var.state

  if not hasattr(local_state, "local_tools"):
    local_state.local_tools = {}

  return local_state.local_tools


def get_local_tool(name: str):
  local_tools = get_local_tools()
  tool_name = resolve_local_tool_name(name)
  return local_tools.get(tool_name)


def set_local_tool(name: str, tool: callable):
  local_tools = get_local_tools()
  tool_name = resolve_local_tool_name(name)

  if tool_name in local_tools:
    raise ValueError(f"Local tool '{name}' already exists.")

  local_tools[tool_name] = tool
  request.get().state.local_tools = local_tools


def is_local_tool(name: str) -> bool:
  local_tools = get_local_tools()
  tool_name = resolve_local_tool_name(name)
  return tool_name in local_tools


def get_hidden_tool_names() -> set:
  """Names of registered tools that are executable but not advertised."""
  request_var = request.get()
  if request_var is None:
    return set()

  local_state = request_var.state

  if not hasattr(local_state, "hidden_local_tools"):
    local_state.hidden_local_tools = set()

  return local_state.hidden_local_tools


def hide_local_tool(name: str) -> None:
  """Stop advertising a tool while keeping it callable through the tool loop."""
  get_hidden_tool_names().add(resolve_local_tool_name(name))


def unhide_local_tool(name: str) -> None:
  get_hidden_tool_names().discard(resolve_local_tool_name(name))


def is_hidden_local_tool(name: str) -> bool:
  return resolve_local_tool_name(name) in get_hidden_tool_names()


def get_hidden_tools() -> dict:
  """Registered tools that are currently hidden, keyed by prefixed name."""
  local_tools = get_local_tools()
  return {
    name: tool
    for name, tool in local_tools.items()
    if name in get_hidden_tool_names()
  }


async def call_local_tool(name: str, **kwargs):
  """
  Calls a local tool by its name with the provided arguments.
  Raises KeyError if the tool does not exist.
  """
  local_tools = get_local_tools()
  tool_name = resolve_local_tool_name(name)

  if tool_name not in local_tools:
    raise KeyError(f"Local tool '{name}' not found.")

  tool = local_tools[tool_name]
  result = tool(**kwargs)

  if inspect.iscoroutinefunction(tool):
    result = await result

  return result


def tool_def_from_fn(fn: callable):
  kws = {
    name:
      (
        parameter.annotation,
        ... if parameter.default == inspect._empty else parameter.default,
      ) for name, parameter in inspect.signature(fn).parameters.items()
  }
  p = create_model(f"`{fn.__name__}`", **kws)

  schema = p.model_json_schema()

  return {
    "type": "function",
    "function":
      {
        "name": resolve_local_tool_name(fn.__name__),
        "description": fn.__doc__,
        "parameters": schema,
      },
  }


def collect_tool_defs():
  """
  Collects all local tools and returns them in OpenAI format.
  """

  local_tools = get_local_tools()
  hidden = get_hidden_tool_names()

  return [
    tool_def_from_fn(tool)
    for name, tool in local_tools.items()
    if name not in hidden
  ]


def resolve_local_tool_name(name: str) -> str:
  """
  Resolves the local tool name by removing the LOCAL_TOOL_PREFIX if it exists.
  """
  if name.startswith(LOCAL_TOOL_PREFIX):
    return name

  return LOCAL_TOOL_PREFIX + name
