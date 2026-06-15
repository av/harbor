import fnmatch
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import config
import log
import research.fetch as fetch
import research.workflow as workflow_mod
import tools.registry
from modules.diffscope import GIT_DIFF_TIMEOUT, is_git_workspace, run_git_diff
from middleware.request_id import request_id_var
from state import request as request_state

ID_PREFIX = 'tools'

DOCS = """
Adds a portable set of request-scoped tools to the downstream LLM. The tools
are registered with Harbor Boost's local tool registry, so the model can call
them during the final completion and Boost will execute them inline.

The module exposes web research tools (`web_search`, `read_url`) plus small
scratchpad utilities (`add_note`, `read_notes`, scratch files, `current_time`,
and `finish`). When `HARBOR_BOOST_WORKSPACE_ROOT` is set, workspace tools
(`read_workspace_file`, `grep_workspace`, `list_workspace_files`, `git_diff_workspace`
when the root is a git repo, and opt-in `write_workspace_file`) are also available.
Web search uses
Tavily when `HARBOR_BOOST_TAVILY_API_KEY` is set, otherwise SearXNG via
`HARBOR_BOOST_SEARXNG_URL`. URL reading uses Jina Reader first and falls back
to direct HTTP text extraction.

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


WORKSPACE_SKIP_DIRS = {
  ".git",
  ".hg",
  ".svn",
  "__pycache__",
  "node_modules",
  ".venv",
  "venv",
  "dist",
  "build",
  ".tox",
  ".mypy_cache",
  ".pytest_cache",
}


def _workspace_base() -> Path:
  if not config.WORKSPACE_ROOT.value:
    raise ValueError("Workspace root is not configured (HARBOR_BOOST_WORKSPACE_ROOT)")
  return Path(config.WORKSPACE_ROOT.value).resolve()


def _workspace_path(file_path: str) -> Path:
  if not file_path or not file_path.strip():
    raise ValueError("file_path is required")

  base = _workspace_base()
  target = (base / file_path.lstrip("/")).resolve()
  if base != target and base not in target.parents:
    raise ValueError("file_path must stay inside the workspace root")

  return target


def _workspace_search_path(path: str = ".") -> Path:
  if not path or not str(path).strip():
    raise ValueError("path is required")

  base = _workspace_base()
  target = (base / str(path).lstrip("/")).resolve()
  if base != target and base not in target.parents:
    raise ValueError("path must stay inside the workspace root")
  if not target.exists():
    raise FileNotFoundError(path)
  return target


def _workspace_glob_matches(rel_path: str, glob_pattern: str | None) -> bool:
  if not glob_pattern:
    return True
  return fnmatch.fnmatch(rel_path, glob_pattern) or fnmatch.fnmatch(
    Path(rel_path).name,
    glob_pattern,
  )


def _iter_workspace_files(search_root: Path, workspace_base: Path, glob_pattern: str | None):
  for root, dirs, files in os.walk(search_root, topdown=True, followlinks=False):
    dirs[:] = [
      directory
      for directory in dirs
      if directory not in WORKSPACE_SKIP_DIRS and not directory.startswith(".")
    ]
    for filename in files:
      if filename.startswith("."):
        continue
      file_path = Path(root) / filename
      rel_path = str(file_path.relative_to(workspace_base))
      if _workspace_glob_matches(rel_path, glob_pattern):
        yield file_path, rel_path


def _grep_workspace_python(
  pattern: str,
  search_root: Path,
  workspace_base: Path,
  glob_pattern: str | None,
  max_matches: int,
) -> list[str]:
  try:
    compiled = re.compile(pattern)
  except re.error as exc:
    raise ValueError(f"Invalid regex pattern: {exc}") from exc

  matches: list[str] = []
  for file_path, rel_path in _iter_workspace_files(search_root, workspace_base, glob_pattern):
    try:
      lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
      continue

    for line_number, line in enumerate(lines, start=1):
      if not compiled.search(line):
        continue
      matches.append(f"{rel_path}:{line_number}:{line.rstrip()}")
      if len(matches) >= max_matches:
        return matches

  return matches


def _grep_workspace_ripgrep(
  pattern: str,
  search_root: Path,
  glob_pattern: str | None,
  max_matches: int,
) -> list[str] | None:
  rg_path = shutil.which("rg")
  if not rg_path:
    return None

  command = [
    rg_path,
    "--no-heading",
    "--line-number",
    "--color",
    "never",
    "--max-count",
    str(max_matches),
    pattern,
    ".",
  ]
  if glob_pattern:
    command.extend(["--glob", glob_pattern])

  try:
    completed = subprocess.run(
      command,
      cwd=search_root,
      capture_output=True,
      text=True,
      timeout=30,
      check=False,
    )
  except (OSError, subprocess.TimeoutExpired):
    return None

  if completed.returncode not in {0, 1}:
    return None

  lines = [line.rstrip() for line in completed.stdout.splitlines() if line.strip()]
  return lines[:max_matches]


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


async def write_workspace_file(file_path: str, content: str) -> str:
  """
  Write a file under the configured workspace root.
  Requires `HARBOR_BOOST_WORKSPACE_ROOT`. Paths are jailed to that directory.
  Opt in by listing `write_workspace_file` in `HARBOR_BOOST_TOOLS`; pair with
  `sightline` for read-before-edit guarding.

  Args:
    file_path (str): Relative workspace file path.
    content (str): Text content to write.
  """
  max_chars = config.WORKSPACE_FILE_MAX_CHARS.value
  if len(content) > max_chars:
    raise ValueError(f"content exceeds {max_chars} characters")

  target = _workspace_path(file_path)
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text(content, encoding="utf-8")
  return f"Wrote {len(content)} characters to {file_path}."


async def grep_workspace(
  pattern: str,
  path: str = ".",
  glob: str | None = None,
  max_matches: int | None = None,
) -> str:
  """
  Search the configured workspace with a ripgrep-style regex pattern.
  Requires `HARBOR_BOOST_WORKSPACE_ROOT`. Paths are jailed to that directory.

  Args:
    pattern (str): Regex pattern to search for.
    path (str): Relative workspace directory or file to search. Default: workspace root.
    glob (str | None): Optional glob filter such as `*.py`.
    max_matches (int | None): Maximum matches to return. Defaults to config cap.
  """
  if not pattern or not pattern.strip():
    raise ValueError("pattern is required")

  search_target = _workspace_search_path(path)
  workspace_base = _workspace_base()
  search_root = search_target if search_target.is_dir() else search_target.parent
  cap = max(1, max_matches or config.WORKSPACE_GREP_MAX_MATCHES.value)

  matches = _grep_workspace_ripgrep(pattern, search_root, glob, cap)
  if matches is None:
    matches = _grep_workspace_python(pattern, search_root, workspace_base, glob, cap)

  if not matches:
    scope = path or "."
    glob_note = f" (glob={glob})" if glob else ""
    return f"No matches for pattern `{pattern}` under `{scope}`{glob_note}."

  output = "\n".join(matches)
  if len(matches) >= cap:
    output += f"\n\n(truncated to {cap} matches)"
  return output


async def list_workspace_files(
  path: str = ".",
  glob: str | None = None,
  max_entries: int | None = None,
) -> str:
  """
  List files under the configured workspace root.
  Requires `HARBOR_BOOST_WORKSPACE_ROOT`. Paths are jailed to that directory.

  Args:
    path (str): Relative workspace directory to list. Default: workspace root.
    glob (str | None): Optional glob filter such as `*.py`.
    max_entries (int | None): Maximum file paths to return. Defaults to config cap.
  """
  search_target = _workspace_search_path(path)
  workspace_base = _workspace_base()
  search_root = search_target if search_target.is_dir() else search_target.parent
  cap = max(1, max_entries or config.WORKSPACE_LIST_MAX_ENTRIES.value)

  entries: list[str] = []
  for _file_path, rel_path in _iter_workspace_files(search_root, workspace_base, glob):
    entries.append(rel_path)
    if len(entries) >= cap:
      break

  if not entries:
    scope = path or "."
    glob_note = f" (glob={glob})" if glob else ""
    return f"No files under `{scope}`{glob_note}."

  output = "\n".join(sorted(entries))
  if len(entries) >= cap:
    output += f"\n\n(truncated to {cap} entries)"
  return output


async def git_diff_workspace(path: str = ".") -> str:
  """
  Return git diff --name-only and --stat for the configured workspace.
  Requires `HARBOR_BOOST_WORKSPACE_ROOT` on a git repository. Paths are jailed
  to that directory. Uses a 5 second timeout.

  Args:
    path (str): Relative workspace directory or file to scope the diff.
      Default: entire workspace.
  """
  workspace_base = _workspace_base()
  if not is_git_workspace(workspace_base):
    raise ValueError("Workspace is not a git repository")

  search_target = _workspace_search_path(path)
  scope_paths: list[str] | None = None
  if search_target != workspace_base:
    scope_paths = [str(search_target.relative_to(workspace_base))]

  result = run_git_diff(
    workspace_base,
    timeout=GIT_DIFF_TIMEOUT,
    paths=scope_paths,
  )
  if result is None:
    return "Git diff unavailable (git command failed or timed out)."

  changed_paths, stat = result
  if not changed_paths and not stat:
    scope_note = f" under `{path}`" if path and path != "." else ""
    return f"No changes in working tree{scope_note}."

  lines = ["<git_diff_name_only>"]
  if changed_paths:
    lines.extend(changed_paths)
  else:
    lines.append("(none)")
  lines.append("</git_diff_name_only>")
  lines.append("")
  lines.append("<git_diff_stat>")
  lines.append(stat or "(none)")
  lines.append("</git_diff_stat>")
  return "\n".join(lines)


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
    available['write_workspace_file'] = write_workspace_file
    available['grep_workspace'] = grep_workspace
    available['list_workspace_files'] = list_workspace_files
    if is_git_workspace():
      available['git_diff_workspace'] = git_diff_workspace

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
    await workflow_mod.complete_or_defer(llm, cfg)
