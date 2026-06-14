"""Read-before-edit guard for Boost scratch file tools."""

import json
from typing import TYPE_CHECKING, Awaitable, Callable

import config
import log
import tools.registry
from modules import tools as tools_module
from state import request as request_state

if TYPE_CHECKING:
  import chat as ch
  import llm as llm_mod

ID_PREFIX = "sightline"

DOCS = """
`sightline` enforces read-before-edit on Boost **scratch** file tools. When paired
after the `tools` module in a workflow, it wraps `read_file`, `write_file`, and
`delete_file` so the model must call `read_file` on a path before mutating it
in the same request.

Per-path read and write generations are tracked in request-scoped state. After a
successful `write_file` or `delete_file`, another read is required before the
next mutation. Creating a brand-new scratch file (path does not yet exist) is
exempt when `allow_create` is enabled.

**When to use**

- Scratch-pad agent workflows using Boost `read_file`, `write_file`, and `delete_file`
- Place **after** `tools` in the module chain so wrappers are registered first
- Does not replace workspace or IDE guards — use `read_workspace_file` separately

**Limitation:** This thin guard only covers Boost scratch tools. It does not
guard `read_workspace_file`, IDE tools, or other external editors.

**Parameters**

- `mode` — `block` rejects mutations without a prior read; `warn` streams a status
  but allows the call. Default: `block`
- `allow_create` — when true, first write to a non-existent scratch path is
  allowed without `read_file`. Default: `true`

```bash
harbor boost modules add tools sightline
harbor config set HARBOR_BOOST_SIGHTLINE_MODE block
harbor config set HARBOR_BOOST_SIGHTLINE_ALLOW_CREATE true
```

**Workflow presets**

- Not included in built-in presets; add manually when scratch read-before-edit is required
- Ad hoc example: `agent-code=tools,sightline,final` via `HARBOR_BOOST_WORKFLOWS`

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


def scratch_file_exists(file_path: str) -> bool:
  try:
    target = tools_module._scratch_path(file_path)
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


def is_create_exempt(file_path: str, *, allow_create: bool | None = None) -> bool:
  if allow_create is None:
    allow_create = config.SIGHTLINE_ALLOW_CREATE.value
  return bool(allow_create) and not scratch_file_exists(file_path)


def block_message(file_path: str, read_gen: int, write_gen: int) -> str:
  payload = {
    "error": "sightline_read_required",
    "message": (
      "Call read_file on this path before write_file or delete_file. "
      "Sightline requires a fresh read after each successful mutation."
    ),
    "path": file_path,
    "canonical_path": canonical_path(file_path),
    "read_generation": read_gen,
    "write_generation": write_gen,
    "required_tool": "read_file",
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
) -> list[str]:
  """Wrap scratch file tools in the local registry. Returns wrapped tool names."""
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

  return wrapped


async def apply(chat: "ch.Chat", llm: "llm_mod.LLM", config: dict | None = None):
  cfg = config or {}
  cfg_final = cfg.get("final", True)
  mode = cfg.get("mode")
  allow_create = cfg.get("allow_create")

  wrapped = install_guards(llm, mode=mode, allow_create=allow_create)
  if wrapped:
    logger.info(f"{ID_PREFIX}: guarding {', '.join(wrapped)}")
    chat.system(
      "Scratch file mutations require read_file on the same path first. "
      "After each write_file or delete_file, call read_file again before the next edit."
    )
  else:
    logger.debug(f"{ID_PREFIX}: no scratch file tools registered to guard")

  if cfg_final:
    await llm.stream_final_completion()