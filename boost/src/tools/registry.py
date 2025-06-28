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

  return [tool_def_from_fn(tool) for tool in local_tools.values()
         ] if local_tools else []


def resolve_local_tool_name(name: str) -> str:
  """
  Resolves the local tool name by removing the LOCAL_TOOL_PREFIX if it exists.
  """
  if name.startswith(LOCAL_TOOL_PREFIX):
    return name

  return LOCAL_TOOL_PREFIX + name
