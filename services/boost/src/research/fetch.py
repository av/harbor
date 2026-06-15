"""Shared web search and URL reading helpers for agentic modules."""

import asyncio
import html
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from urllib.parse import parse_qs, urlparse

import httpx

import config
import log

logger = log.setup_logger(__name__)

USER_AGENT = "Harbor Boost tools (+https://github.com/av/harbor)"

SEARCH_FAILED_PREFIX = "Web search failed:"
SEARCH_UNAVAILABLE_PREFIX = "Web search unavailable:"
READ_FAILED_PREFIX = "Could not read URL:"

_TRANSIENT_HTTP_ERRORS = (httpx.TimeoutException, httpx.ConnectError)
_RETRY_BACKOFF_SECONDS = 1.0

_T = TypeVar("_T")


def _is_transient_failure(exc: BaseException) -> bool:
  return isinstance(exc, _TRANSIENT_HTTP_ERRORS)


async def _with_transient_retry(
  operation: str,
  coro_fn: Callable[[], Awaitable[_T]],
) -> _T:
  """Run ``coro_fn`` once; on transient HTTP failure, wait and retry once."""
  try:
    return await coro_fn()
  except Exception as exc:
    if not _is_transient_failure(exc):
      raise
    logger.warning(
      f"{operation} failed with transient error ({exc}); "
      f"retrying in {_RETRY_BACKOFF_SECONDS:g}s",
    )
    await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
    return await coro_fn()


def trim(text: str, max_chars: int) -> str:
  if len(text) <= max_chars:
    return text
  return f"{text[:max_chars]}\n\n[truncated to {max_chars} characters]"


def trim_note(note: str, max_chars: int | None = None) -> str:
  """Trim a research-brief note to the configured character limit."""
  text = (note or "").strip()
  if not text:
    return ""
  limit = config.RESEARCH_NOTES_MAX_CHARS.value if max_chars is None else max_chars
  if limit <= 0:
    return text
  return trim(text, limit)


def _is_internal_address(hostname: str) -> bool:
  try:
    for info in socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM):
      addr = ipaddress.ip_address(info[4][0])
      if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        return True
  except (socket.gaierror, ValueError):
    return True
  return False


def require_http_url(url: str) -> str:
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


def is_search_failure_result(text: str) -> bool:
  """Return True when search output indicates failure, timeout, or no results."""
  text = (text or "").strip()
  if not text or text == "No results found.":
    return True
  return any(text.startswith(prefix) for prefix in (SEARCH_FAILED_PREFIX, SEARCH_UNAVAILABLE_PREFIX))


def is_read_failure_result(text: str) -> bool:
  """Return True when read_url returned an error message instead of page content."""
  return (text or "").strip().startswith(READ_FAILED_PREFIX)


def format_search_results(results: list[dict[str, Any]]) -> str:
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

  return format_search_results(data.get("results", []))


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

  return format_search_results(data.get("results", [])[:max_results])


async def web_search(query: str, *, max_results: int | None = None) -> str:
  """
  Search the live web and return a short ranked result set.

  Args:
    query (str): Search query.
    max_results (int | None): Result cap. Defaults to TOOLS_SEARCH_MAX_RESULTS.
  """
  limit = max(1, max_results or config.TOOLS_SEARCH_MAX_RESULTS.value)

  async def _run_search() -> str:
    if config.TAVILY_API_KEY.value:
      return await _search_tavily(query, limit)
    return await _search_searxng(query, limit)

  try:
    return await _with_transient_retry("web_search", _run_search)
  except Exception as e:
    logger.error(f"web_search failed: {e}")
    return f"Web search failed: {e}"


async def read_url(url: str, *, max_chars: int | None = None) -> str:
  """
  Read the text content of a web page by URL.

  Args:
    url (str): Absolute http or https URL to read.
    max_chars (int | None): Character cap. Defaults to TOOLS_READ_MAX_CHARS.
  """
  try:
    url = require_http_url(url)
  except ValueError as e:
    logger.warning(f"read_url rejected {url}: {e}")
    return f"{READ_FAILED_PREFIX} {url}: {e}"

  limit = max_chars or config.TOOLS_READ_MAX_CHARS.value

  async def _run_jina_read() -> str:
    return await _read_with_jina(url)

  async def _run_direct_read() -> str:
    return await _read_direct(url)

  try:
    content = await _with_transient_retry("read_url", _run_jina_read)
  except Exception as e:
    logger.warning(f"Jina read failed for {url}: {e}; falling back to direct HTTP")
    try:
      content = await _with_transient_retry("read_url", _run_direct_read)
    except Exception as direct_error:
      logger.error(f"read_url failed for {url}: {direct_error}")
      return f"{READ_FAILED_PREFIX} {url}: {direct_error}"

  return trim(content, limit)