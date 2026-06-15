"""Read-before-edit guard for Boost scratch and workspace file tools."""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Literal

import config
import log
import research.workflow as workflow_mod
import tools.registry
from modules import tools as tools_module
from state import request as request_state

if TYPE_CHECKING:
  import chat as ch
  import llm as llm_mod

ID_PREFIX = "sightline"

DOCS = """
`sightline` enforces read-before-edit on Boost **scratch** and **workspace** file
tools. When paired after the `tools` module in a workflow, it wraps `read_file`,
`write_file`, and `delete_file` so the model must call `read_file` on a path
before mutating it in the same request.

When `HARBOR_BOOST_WORKSPACE_ROOT` is set (and workspace guarding is enabled),
`sightline` also wraps `read_workspace_file` and, when registered,
`write_workspace_file` using the same per-path generation tracking.

Per-path read and write generations are tracked in request-scoped state. After a
successful `write_file` or `delete_file`, another read is required before the
next mutation. Creating a brand-new scratch file (path does not yet exist) is
exempt when `allow_create` is enabled.

**When to use**

- Scratch-pad agent workflows using Boost `read_file`, `write_file`, and `delete_file`
- Workspace-aware coding sandboxes with `read_workspace_file` and opt-in
  `write_workspace_file` (list both in `HARBOR_BOOST_TOOLS`)
- Place **after** `tools` in the module chain so wrappers are registered first

**Limitation:** Workspace writes are opt-in — add `write_workspace_file` to
`HARBOR_BOOST_TOOLS` when the sandbox should allow edits. IDE tools and other
external editors are out of scope.

**Parameters**

- `mode` — `block` rejects mutations without a prior read; `warn` streams a status
  but allows the call. Default: `block`
- `allow_create` — when true, first write to a non-existent scratch path is
  allowed without `read_file`. Default: `true`
- `workspace` — when true and a workspace root is configured, guard workspace file
  tools. Default: `true` when `HARBOR_BOOST_WORKSPACE_ROOT` is set

```bash
harbor boost modules add tools sightline
harbor config set HARBOR_BOOST_SIGHTLINE_MODE block
harbor config set HARBOR_BOOST_SIGHTLINE_ALLOW_CREATE true
harbor config set HARBOR_BOOST_SIGHTLINE_WORKSPACE true
```

**Workflow presets**

- `agent-code` (`tools`, `sightline`, `diffscope`, `autocheck`, `final`) — sandbox read-before-edit

**Standalone**

```bash
docker run \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \\
  -e "HARBOR_BOOST_MODULES=tools,sightline" \\
  -e "HARBOR_BOOST_SIGHTLINE_MODE=block" \\
  -p 8004:8000 \\
  ghcr.io/av/harbor-boost:latest
```
"""

logger = log.setup_logger(ID_PREFIX)

PathState = dict[str, dict[str, int]]
ToolKind = Literal["scratch", "workspace"]
WORKSPACE_PATH_PREFIX = "workspace:"


def _request_store(name: str, default):
  request = request_state.get()
  if request is None:
    return default

  if not hasattr(request.state, name):
    setattr(request.state, name, default)

  return getattr(request.state, name)


def _path_state() -> PathState:
  return _request_store("sightline_path_state", {})


def _next_sequence() -> int:
  request = request_state.get()
  if request is None:
    return 0

  current = getattr(request.state, "sightline_seq", 0)
  current += 1
  setattr(request.state, "sightline_seq", current)
  return current


def canonical_path(file_path: str) -> str:
  """Normalize a scratch path for generation tracking."""
  try:
    target = tools_module._scratch_path(file_path)
    base = tools_module._scratch_base()
    return str(target.relative_to(base))
  except ValueError:
    return (file_path or "").strip().lstrip("/")


def workspace_canonical_path(file_path: str) -> str:
  """Normalize a workspace path for generation tracking."""
  try:
    target = tools_module._workspace_path(file_path)
    base = Path(config.WORKSPACE_ROOT.value).resolve()
    relative = str(target.relative_to(base))
  except ValueError:
    relative = (file_path or "").strip().lstrip("/")
  return f"{WORKSPACE_PATH_PREFIX}{relative}"


def tracking_path(file_path: str, *, kind: ToolKind = "scratch") -> str:
  if kind == "workspace":
    return workspace_canonical_path(file_path)
  return canonical_path(file_path)


def workspace_guard_enabled(workspace: bool | None = None) -> bool:
  if not config.WORKSPACE_ROOT.value:
    return False
  if workspace is not None:
    return workspace
  return config.SIGHTLINE_WORKSPACE.value


def workspace_guard_skip_reason(workspace: bool | None = None) -> str | None:
  """Return a skip reason when workspace tools are not guarded, else None."""
  if not config.WORKSPACE_ROOT.value:
    return "no_workspace_root"
  if workspace_guard_enabled(workspace):
    return None
  return "workspace_guard_disabled"


def scratch_file_exists(file_path: str) -> bool:
  try:
    target = tools_module._scratch_path(file_path)
    return target.exists() and target.is_file()
  except ValueError:
    return False


def workspace_file_exists(file_path: str) -> bool:
  try:
    target = tools_module._workspace_path(file_path)
    return target.exists() and target.is_file()
  except ValueError:
    return False


def get_generations(path: str) -> tuple[int, int]:
  entry = _path_state().get(path, {"read": 0, "write": 0})
  return entry.get("read", 0), entry.get("write", 0)


def record_read(path: str) -> int:
  state = _path_state()
  entry = state.setdefault(path, {"read": 0, "write": 0})
  entry["read"] = _next_sequence()
  logger.debug(f"{ID_PREFIX}: read {path} -> generation {entry['read']}")
  return entry["read"]


def record_write(path: str) -> int:
  state = _path_state()
  entry = state.setdefault(path, {"read": 0, "write": 0})
  entry["write"] = _next_sequence()
  logger.debug(f"{ID_PREFIX}: write {path} -> generation {entry['write']}")
  return entry["write"]


def can_mutate(path: str) -> bool:
  read_gen, write_gen = get_generations(path)
  return read_gen > write_gen


def is_create_exempt(
  file_path: str,
  *,
  allow_create: bool | None = None,
  kind: ToolKind = "scratch",
) -> bool:
  if allow_create is None:
    allow_create = config.SIGHTLINE_ALLOW_CREATE.value
  if not allow_create:
    return False
  if kind == "workspace":
    return not workspace_file_exists(file_path)
  return not scratch_file_exists(file_path)


def block_message(
  file_path: str,
  read_gen: int,
  write_gen: int,
  *,
  kind: ToolKind = "scratch",
) -> str:
  if kind == "workspace":
    required_tool = "read_workspace_file"
    mutation_tools = "write_workspace_file"
    canonical = workspace_canonical_path(file_path)
  else:
    required_tool = "read_file"
    mutation_tools = "write_file or delete_file"
    canonical = canonical_path(file_path)

  payload = {
    "error": "sightline_read_required",
    "message": (
      f"Call {required_tool} on this path before {mutation_tools}. "
      "Sightline requires a fresh read after each successful mutation."
    ),
    "path": file_path,
    "canonical_path": canonical,
    "read_generation": read_gen,
    "write_generation": write_gen,
    "required_tool": required_tool,
    "tool_kind": kind,
  }
  return json.dumps(payload, indent=2)


def _replace_local_tool(name: str, tool: Callable[..., Awaitable[str] | str]) -> None:
  local_tools = tools.registry.get_local_tools()
  tool_name = tools.registry.resolve_local_tool_name(name)
  local_tools[tool_name] = tool


def _resolve_base_tool(name: str) -> Callable[..., Awaitable[str] | str] | None:
  existing = tools.registry.get_local_tool(name)
  if existing is not None and not getattr(existing, "_sightline_wrapped", False):
    return existing

  if existing is not None and getattr(existing, "_sightline_unwrapped", None):
    return existing._sightline_unwrapped

  base = getattr(tools_module, name, None)
  if base is not None:
    return base

  return None


def _wrap_read_file(
  base_fn: Callable[..., Awaitable[str]],
  llm: "llm_mod.LLM",
) -> Callable[..., Awaitable[str]]:
  async def guarded_read_file(file_path: str) -> str:
    result = await base_fn(file_path)
    record_read(canonical_path(file_path))
    return result

  guarded_read_file.__name__ = "read_file"
  guarded_read_file.__doc__ = base_fn.__doc__
  guarded_read_file._sightline_wrapped = True
  guarded_read_file._sightline_unwrapped = base_fn
  return guarded_read_file


def _wrap_read_workspace_file(
  base_fn: Callable[..., Awaitable[str]],
  llm: "llm_mod.LLM",
) -> Callable[..., Awaitable[str]]:
  async def guarded_read_workspace_file(file_path: str) -> str:
    result = await base_fn(file_path)
    record_read(workspace_canonical_path(file_path))
    return result

  guarded_read_workspace_file.__name__ = "read_workspace_file"
  guarded_read_workspace_file.__doc__ = base_fn.__doc__
  guarded_read_workspace_file._sightline_wrapped = True
  guarded_read_workspace_file._sightline_unwrapped = base_fn
  return guarded_read_workspace_file


def _wrap_write_file(
  base_fn: Callable[..., Awaitable[str]],
  llm: "llm_mod.LLM",
  *,
  mode: str | None = None,
  allow_create: bool | None = None,
) -> Callable[..., Awaitable[str]]:
  async def guarded_write_file(file_path: str, content: str) -> str:
    path = canonical_path(file_path)
    read_gen, write_gen = get_generations(path)

    if not is_create_exempt(file_path, allow_create=allow_create) and not can_mutate(path):
      message = block_message(file_path, read_gen, write_gen)
      logger.warning(f"{ID_PREFIX}: blocked write_file for {path}")
      await llm.emit_status(f"Sightline: blocked write_file on {path} — read_file required")
      if (mode or config.SIGHTLINE_MODE.value).lower() == "warn":
        logger.warning(f"{ID_PREFIX}: warn mode allowing write_file on {path}")
      else:
        raise ValueError(message)

    result = await base_fn(file_path, content)
    record_write(path)
    return result

  guarded_write_file.__name__ = "write_file"
  guarded_write_file.__doc__ = base_fn.__doc__
  guarded_write_file._sightline_wrapped = True
  guarded_write_file._sightline_unwrapped = base_fn
  return guarded_write_file


def _wrap_write_workspace_file(
  base_fn: Callable[..., Awaitable[str]],
  llm: "llm_mod.LLM",
  *,
  mode: str | None = None,
  allow_create: bool | None = None,
) -> Callable[..., Awaitable[str]]:
  async def guarded_write_workspace_file(file_path: str, content: str) -> str:
    path = workspace_canonical_path(file_path)
    read_gen, write_gen = get_generations(path)

    if (
      not is_create_exempt(file_path, allow_create=allow_create, kind="workspace")
      and not can_mutate(path)
    ):
      message = block_message(file_path, read_gen, write_gen, kind="workspace")
      logger.warning(f"{ID_PREFIX}: blocked write_workspace_file for {path}")
      await llm.emit_status(
        f"Sightline: blocked write_workspace_file on {path} — read_workspace_file required"
      )
      if (mode or config.SIGHTLINE_MODE.value).lower() == "warn":
        logger.warning(f"{ID_PREFIX}: warn mode allowing write_workspace_file on {path}")
      else:
        raise ValueError(message)

    result = await base_fn(file_path, content)
    record_write(path)
    return result

  guarded_write_workspace_file.__name__ = "write_workspace_file"
  guarded_write_workspace_file.__doc__ = base_fn.__doc__
  guarded_write_workspace_file._sightline_wrapped = True
  guarded_write_workspace_file._sightline_unwrapped = base_fn
  return guarded_write_workspace_file


def _wrap_delete_file(
  base_fn: Callable[..., Awaitable[str]],
  llm: "llm_mod.LLM",
  *,
  mode: str | None = None,
) -> Callable[..., Awaitable[str]]:
  async def guarded_delete_file(file_path: str) -> str:
    path = canonical_path(file_path)
    read_gen, write_gen = get_generations(path)

    if not can_mutate(path):
      message = block_message(file_path, read_gen, write_gen)
      logger.warning(f"{ID_PREFIX}: blocked delete_file for {path}")
      await llm.emit_status(f"Sightline: blocked delete_file on {path} — read_file required")
      if (mode or config.SIGHTLINE_MODE.value).lower() == "warn":
        logger.warning(f"{ID_PREFIX}: warn mode allowing delete_file on {path}")
      else:
        raise ValueError(message)

    result = await base_fn(file_path)
    record_write(path)
    return result

  guarded_delete_file.__name__ = "delete_file"
  guarded_delete_file.__doc__ = base_fn.__doc__
  guarded_delete_file._sightline_wrapped = True
  guarded_delete_file._sightline_unwrapped = base_fn
  return guarded_delete_file


def install_guards(
  llm: "llm_mod.LLM",
  *,
  mode: str | None = None,
  allow_create: bool | None = None,
  workspace: bool | None = None,
) -> list[str]:
  """Wrap scratch and workspace file tools in the local registry."""
  wrapped: list[str] = []

  read_base = _resolve_base_tool("read_file")
  if read_base is not None:
    _replace_local_tool("read_file", _wrap_read_file(read_base, llm))
    wrapped.append("read_file")

  write_base = _resolve_base_tool("write_file")
  if write_base is not None:
    _replace_local_tool(
      "write_file",
      _wrap_write_file(write_base, llm, mode=mode, allow_create=allow_create),
    )
    wrapped.append("write_file")

  delete_base = _resolve_base_tool("delete_file")
  if delete_base is not None:
    _replace_local_tool(
      "delete_file",
      _wrap_delete_file(delete_base, llm, mode=mode),
    )
    wrapped.append("delete_file")

  if workspace_guard_enabled(workspace):
    read_workspace_base = _resolve_base_tool("read_workspace_file")
    if read_workspace_base is not None:
      _replace_local_tool(
        "read_workspace_file",
        _wrap_read_workspace_file(read_workspace_base, llm),
      )
      wrapped.append("read_workspace_file")

    write_workspace_base = _resolve_base_tool("write_workspace_file")
    if write_workspace_base is not None:
      _replace_local_tool(
        "write_workspace_file",
        _wrap_write_workspace_file(
          write_workspace_base,
          llm,
          mode=mode,
          allow_create=allow_create,
        ),
      )
      wrapped.append("write_workspace_file")

  return wrapped


async def apply(chat: "ch.Chat", llm: "llm_mod.LLM", config: dict | None = None):
  cfg = config or {}
  cfg_final = cfg.get("final", True)
  mode = cfg.get("mode")
  allow_create = cfg.get("allow_create")
  workspace = cfg.get("workspace")

  wrapped = install_guards(
    llm,
    mode=mode,
    allow_create=allow_create,
    workspace=workspace,
  )
  workspace_skip = workspace_guard_skip_reason(workspace)
  if workspace_skip == "workspace_guard_disabled":
    logger.debug(f"{ID_PREFIX}: Pass-through — {workspace_skip}")

  if wrapped:
    logger.info(f"{ID_PREFIX}: guarding {', '.join(wrapped)}")
    messages = [
      "Scratch file mutations require read_file on the same path first. "
      "After each write_file or delete_file, call read_file again before the next edit."
    ]
    if workspace_guard_enabled(workspace) and "read_workspace_file" in wrapped:
      messages.append(
        "Workspace file mutations require read_workspace_file on the same path first. "
        "After each write_workspace_file, call read_workspace_file again before the next edit."
      )
    chat.system(" ".join(messages))
  else:
    logger.debug(f"{ID_PREFIX}: Pass-through — no_file_tools_registered")

  defer_final = cfg.get("defer_final", not cfg_final)
  return await workflow_mod.complete_or_defer(llm, {**cfg, "defer_final": defer_final})