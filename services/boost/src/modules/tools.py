from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import config
import log
import research.fetch as fetch
import tools.registry
from middleware.request_id import request_id_var
from state import request as request_state

ID_PREFIX = 'tools'

DOCS = """
Adds a portable set of request-scoped tools to the downstream LLM. The tools
are registered with Harbor Boost's local tool registry, so the model can call
them during the final completion and Boost will execute them inline.

The module exposes web research tools (`web_search`, `read_url`) plus small
scratchpad utilities (`add_note`, `read_notes`, scratch files, `current_time`,
and `finish`). Web search uses Tavily when `HARBOR_BOOST_TAVILY_API_KEY` is
set, otherwise SearXNG via `HARBOR_BOOST_SEARXNG_URL`. URL reading uses Jina
Reader first and falls back to direct HTTP text extraction.

The module is workflow-aware: when it is placed before another workflow module,
the workflow runner configures it as a setup step so tools are registered before
the final completion. Ad hoc requests can also pass a workflow through
`@boost_workflow` on the chat completion body.

```bash
harbor boost modules add tools
harbor config set HARBOR_BOOST_TOOLS "web_search;read_url;current_time"
harbor config set HARBOR_BOOST_SEARXNG_URL http://searxng:8080
```

**Standalone**

```bash
docker run \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \\
  -e "HARBOR_BOOST_MODULES=tools" \\
  -e "HARBOR_BOOST_SEARXNG_URL=http://host.docker.internal:33811" \\
  -p 8004:8000 \\
  ghcr.io/av/harbor-boost:latest
```
"""

logger = log.setup_logger(ID_PREFIX)

DEFAULT_TOOLS = {
  'web_search',
  'read_url',
  'current_time',
  'add_note',
  'read_notes',
  'write_file',
  'read_file',
  'list_files',
  'delete_file',
  'clear_files',
  'finish',
}


def _request_store(name: str, default):
  request = request_state.get()
  if request is None:
    return default

  if not hasattr(request.state, name):
    setattr(request.state, name, default)

  return getattr(request.state, name)


def _scratch_base() -> Path:
  request_id = request_id_var.get() or "default"
  base = Path("/tmp/harbor-boost-tools") / request_id
  base.mkdir(parents=True, exist_ok=True)
  return base


def _scratch_path(file_path: str) -> Path:
  if not file_path or not file_path.strip():
    raise ValueError("file_path is required")

  base = _scratch_base().resolve()
  target = (base / file_path.lstrip("/")).resolve()
  if base != target and base not in target.parents:
    raise ValueError("file_path must stay inside the scratch directory")

  return target


async def web_search(query: str) -> str:
  """
  Search the live web and return a short ranked result set.
  Use absolute dates for time-sensitive searches because search engines do not
  know the user's current date unless you include it in the query.

  Args:
    query (str): Search query.
  """
  return await fetch.web_search(
    query,
    max_results=max(1, config.TOOLS_SEARCH_MAX_RESULTS.value),
  )


async def read_url(url: str) -> str:
  """
  Read the text content of a web page by URL.
  Search results only contain snippets; use this tool when full page content is
  needed. Some websites may block automated reads.

  Args:
    url (str): Absolute http or https URL to read.
  """
  return await fetch.read_url(url, max_chars=config.TOOLS_READ_MAX_CHARS.value)


async def current_time(timezone: str = "UTC") -> str:
  """
  Return the current date and time in a named timezone.

  Args:
    timezone (str): IANA timezone name such as UTC, Europe/Warsaw, or America/New_York.
  """
  try:
    tz = ZoneInfo(timezone)
  except ZoneInfoNotFoundError:
    raise ValueError(f"Unknown timezone: {timezone}")

  return datetime.now(tz).isoformat()


async def add_note(note: str) -> str:
  """
  Add a short request-scoped scratch note.

  Args:
    note (str): Note to remember during this completion.
  """
  notes = _request_store("boost_tool_notes", [])
  notes.append(note)
  return f"Added note {len(notes)}."


async def read_notes() -> str:
  """
  Read request-scoped scratch notes written during this completion.
  """
  notes = _request_store("boost_tool_notes", [])
  if not notes:
    return "No notes."
  return "\n".join(f"{idx}. {note}" for idx, note in enumerate(notes, start=1))


async def write_file(file_path: str, content: str) -> str:
  """
  Write a request-scoped scratch file. Files disappear when the container /tmp is cleared.

  Args:
    file_path (str): Relative scratch file path.
    content (str): Text content to write.
  """
  max_chars = config.TOOLS_FILE_MAX_CHARS.value
  if len(content) > max_chars:
    raise ValueError(f"content exceeds {max_chars} characters")

  target = _scratch_path(file_path)
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text(content, encoding="utf-8")
  return f"Wrote {len(content)} characters to {file_path}."


async def read_file(file_path: str) -> str:
  """
  Read a request-scoped scratch file.

  Args:
    file_path (str): Relative scratch file path.
  """
  target = _scratch_path(file_path)
  if not target.exists() or not target.is_file():
    raise FileNotFoundError(file_path)
  return fetch.trim(target.read_text(encoding="utf-8"), config.TOOLS_FILE_MAX_CHARS.value)


def _workspace_path(file_path: str) -> Path:
  if not config.WORKSPACE_ROOT.value:
    raise ValueError("Workspace root is not configured (HARBOR_BOOST_WORKSPACE_ROOT)")

  if not file_path or not file_path.strip():
    raise ValueError("file_path is required")

  base = Path(config.WORKSPACE_ROOT.value).resolve()
  target = (base / file_path.lstrip("/")).resolve()
  if base != target and base not in target.parents:
    raise ValueError("file_path must stay inside the workspace root")

  return target


async def read_workspace_file(file_path: str) -> str:
  """
  Read a file from the configured workspace root.
  Requires `HARBOR_BOOST_WORKSPACE_ROOT`. Paths are jailed to that directory.

  Args:
    file_path (str): Relative workspace file path.
  """
  target = _workspace_path(file_path)
  if not target.exists() or not target.is_file():
    raise FileNotFoundError(file_path)
  return fetch.trim(
    target.read_text(encoding="utf-8"),
    config.WORKSPACE_FILE_MAX_CHARS.value,
  )


async def list_files() -> str:
  """
  List request-scoped scratch files.
  """
  base = _scratch_base()
  files = [str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()]
  if not files:
    return "No files."
  return "\n".join(sorted(files))


async def delete_file(file_path: str) -> str:
  """
  Delete a request-scoped scratch file.

  Args:
    file_path (str): Relative scratch file path.
  """
  target = _scratch_path(file_path)
  if not target.exists() or not target.is_file():
    raise FileNotFoundError(file_path)
  target.unlink()
  return f"Deleted {file_path}."


async def clear_files() -> str:
  """
  Delete all request-scoped scratch files.
  """
  base = _scratch_base()
  deleted = 0
  for path in sorted(base.rglob("*"), reverse=True):
    if path.is_file():
      path.unlink()
      deleted += 1
    elif path.is_dir() and path != base:
      path.rmdir()
  return f"Deleted {deleted} file(s)."


async def finish(answer: str) -> str:
  """
  Return the final answer when the model is done using tools.

  Args:
    answer (str): Final answer to provide to the user.
  """
  return answer


def _selected_tools(configured_tools: list[str] | None = None) -> dict[str, Callable]:
  available = {
    'web_search': web_search,
    'read_url': read_url,
    'current_time': current_time,
    'add_note': add_note,
    'read_notes': read_notes,
    'write_file': write_file,
    'read_file': read_file,
    'list_files': list_files,
    'delete_file': delete_file,
    'clear_files': clear_files,
    'finish': finish,
  }

  if config.WORKSPACE_ROOT.value:
    available['read_workspace_file'] = read_workspace_file

  configured = set(configured_tools) if configured_tools else set(config.TOOLS.value) if config.TOOLS.value else DEFAULT_TOOLS
  selected = {}
  for name in configured:
    tool = available.get(name)
    if tool is None:
      logger.warning(f"Unknown tool configured: {name}")
      continue
    selected[name] = tool
  return selected


async def apply(chat, llm, config: dict | None = None):
  cfg = config or {}
  cfg_final = cfg.get("final", True)
  configured_tools = cfg.get("tools")

  for name, tool in _selected_tools(configured_tools).items():
    try:
      tools.registry.set_local_tool(name, tool)
    except ValueError:
      logger.debug(f"Tool '{name}' already registered, skipping")

  chat.system(
    "You may use the provided tools when they help answer accurately. "
    "Use web_search for current or external information, read_url for full page content, "
    "current_time when dates matter, and scratch notes/files for temporary organization. "
    "When using search for time-sensitive information, include absolute dates in the query."
  )

  if cfg_final:
    await llm.stream_final_completion()
