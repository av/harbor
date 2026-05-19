import html
import ipaddress
import re
import socket
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

import config
import log
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

USER_AGENT = "Harbor Boost tools (+https://github.com/av/harbor)"
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


def _trim(text: str, max_chars: int) -> str:
  if len(text) <= max_chars:
    return text
  return f"{text[:max_chars]}\n\n[truncated to {max_chars} characters]"


def _is_internal_address(hostname: str) -> bool:
  try:
    for info in socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM):
      addr = ipaddress.ip_address(info[4][0])
      if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        return True
  except (socket.gaierror, ValueError):
    return True
  return False


def _require_http_url(url: str) -> str:
  parsed = urlparse(url)
  if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
    raise ValueError("URL must be absolute and use http or https")
  hostname = parsed.hostname or ""
  if _is_internal_address(hostname):
    raise ValueError("URLs targeting internal or private network addresses are not allowed")
  return url


def _strip_html(raw: str) -> str:
  text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", raw)
  text = re.sub(r"(?s)<[^>]+>", " ", text)
  text = html.unescape(text)
  return re.sub(r"\s+", " ", text).strip()


async def _read_with_jina(url: str) -> str:
  if not config.JINA_READER_API_URL.value:
    raise ValueError("Jina Reader API URL is not configured")

  headers = {"X-Retain-Images": "none", "User-Agent": USER_AGENT}
  if config.JINA_READER_API_KEY.value:
    headers["Authorization"] = f"Bearer {config.JINA_READER_API_KEY.value}"

  endpoint = f"{config.JINA_READER_API_URL.value.rstrip('/')}/{url}"
  async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
    response = await client.get(endpoint, headers=headers)
    response.raise_for_status()
    return response.text


async def _read_direct(url: str) -> str:
  async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
    response = await client.get(url, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" in content_type:
      return _strip_html(response.text)
    return response.text


def _format_search_results(results: list[dict[str, Any]]) -> str:
  if not results:
    return "No results found."

  lines = []
  for idx, result in enumerate(results, start=1):
    title = result.get("title") or "Untitled"
    url = result.get("url") or result.get("link") or ""
    snippet = result.get("content") or result.get("snippet") or result.get("description") or ""
    published = result.get("published_date") or result.get("publishedDate") or "Date: N/A"
    lines.append(f"{idx}. [{title}]({url}) ({published})\n{snippet}".strip())

  return "\n".join(lines)


async def _search_tavily(query: str, max_results: int) -> str:
  payload = {
    "api_key": config.TAVILY_API_KEY.value,
    "query": query,
    "max_results": max_results,
    "include_answer": False,
    "include_raw_content": False,
  }

  async with httpx.AsyncClient(timeout=30.0) as client:
    response = await client.post("https://api.tavily.com/search", json=payload)
    response.raise_for_status()
    data = response.json()

  return _format_search_results(data.get("results", []))


async def _search_searxng(query: str, max_results: int) -> str:
  if not config.SEARXNG_URL.value:
    return "Web search unavailable: configure HARBOR_BOOST_TAVILY_API_KEY or HARBOR_BOOST_SEARXNG_URL."

  params = {
    "q": query,
    "format": "json",
    "language": "en",
    "pageno": 1,
    "results": max_results,
  }
  for key, values in parse_qs(config.SEARXNG_QUERY_PARAMS.value).items():
    if values:
      params[key] = values[-1]

  endpoint = f"{config.SEARXNG_URL.value.rstrip('/')}/search"
  async with httpx.AsyncClient(timeout=30.0) as client:
    response = await client.get(endpoint, params=params)
    response.raise_for_status()
    data = response.json()

  return _format_search_results(data.get("results", [])[:max_results])


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
  max_results = max(1, config.TOOLS_SEARCH_MAX_RESULTS.value)

  try:
    if config.TAVILY_API_KEY.value:
      return await _search_tavily(query, max_results)
    return await _search_searxng(query, max_results)
  except Exception as e:
    logger.error(f"web_search failed: {e}")
    return f"Web search failed: {e}"


async def read_url(url: str) -> str:
  """
  Read the text content of a web page by URL.
  Search results only contain snippets; use this tool when full page content is
  needed. Some websites may block automated reads.

  Args:
    url (str): Absolute http or https URL to read.
  """
  url = _require_http_url(url)

  try:
    content = await _read_with_jina(url)
  except Exception as e:
    logger.warning(f"Jina read failed for {url}: {e}; falling back to direct HTTP")
    content = await _read_direct(url)

  return _trim(content, config.TOOLS_READ_MAX_CHARS.value)


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
  return _trim(target.read_text(encoding="utf-8"), config.TOOLS_FILE_MAX_CHARS.value)


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
    tools.registry.set_local_tool(name, tool)

  chat.system(
    "You may use the provided tools when they help answer accurately. "
    "Use web_search for current or external information, read_url for full page content, "
    "current_time when dates matter, and scratch notes/files for temporary organization. "
    "When using search for time-sensitive information, include absolute dates in the query."
  )

  if cfg_final:
    await llm.stream_final_completion()
