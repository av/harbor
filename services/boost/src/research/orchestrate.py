"""Shared research orchestration for agentic Boost modules."""

import asyncio
import re
from typing import TYPE_CHECKING, Awaitable, TypeVar

from pydantic import BaseModel, Field

import config
import deliverable
import log
import research.brief as brief_mod
import research.budget as budget_mod
import research.fetch as fetch

if TYPE_CHECKING:
  import chat as ch
  import llm

logger = log.setup_logger(__name__)

SEARCH_CONCURRENCY = 2
URL_READ_CONCURRENCY = 3

_T = TypeVar("_T")

CONTINUATION_RE = re.compile(
  r"\b(?:continue|keep\s+going|go\s+on|proceed|carry\s+on|as\s+planned|same\s+as\s+before)\b",
  re.IGNORECASE,
)


def last_user_text(chat: "ch.Chat") -> str:
  node = chat.match_one(role="user", index=-1)
  return (node.content or "").strip() if node else ""


def low_value_skip_reason(chat: "ch.Chat") -> str | None:
  """Return a skip reason for acks and short continuations, or None to proceed."""
  text = last_user_text(chat)
  if not text or len(text) < 4:
    return "empty_or_short_message"
  if deliverable.is_acknowledgment(text):
    return "acknowledgment"
  if CONTINUATION_RE.search(text) and len(text) < 120:
    return "continuation"
  return None


def should_skip_low_value_turn(chat: "ch.Chat") -> bool:
  """Skip research and similar modules on acks and short continuations."""
  return low_value_skip_reason(chat) is not None


def cheap_llm(llm: "llm.LLM") -> "llm.LLM":
  """Bare downstream client for inexpensive internal completions."""
  import llm as llm_mod

  return llm_mod.LLM(
    url=llm.url,
    headers=llm.headers,
    query_params=llm.query_params,
    model=llm.model,
    params={},
    messages=[{"role": "user", "content": ""}],
    module=None,
  )


def dedupe_queries(queries: list[str], *, limit: int) -> list[str]:
  cleaned = []
  seen = set()
  for query in queries:
    query = (query or "").strip()
    if not query:
      continue
    key = query.lower()
    if key in seen:
      continue
    seen.add(key)
    cleaned.append(query)
  return cleaned[:limit]


def page_read_char_limit(budget: budget_mod.ResearchBudget) -> int:
  remaining = budget.remaining_chars()
  if budget.max_url_reads <= 0:
    return remaining
  return max(1000, remaining // max(1, budget.max_url_reads))


async def emit_research_status(llm: "llm.LLM | None", status: str) -> None:
  if llm is not None:
    await llm.emit_status(status)


def content_chars_in_brief(brief: brief_mod.ResearchBrief) -> int:
  """Return total snippet characters gathered from searches and page reads."""
  return sum(len(source.snippet or "") for source in [*brief.searches, *brief.pages])


async def _gather_with_concurrency(
  coros: list[Awaitable[_T]],
  *,
  limit: int,
) -> list[_T]:
  if not coros:
    return []

  semaphore = asyncio.Semaphore(max(1, limit))

  async def _run(coro: Awaitable[_T]) -> _T:
    async with semaphore:
      return await coro

  return await asyncio.gather(*[_run(coro) for coro in coros])


def urls_from_brief(brief: brief_mod.ResearchBrief) -> list[str]:
  urls = []
  seen = set()
  for source in [*brief.searches, *brief.pages]:
    url = (source.url or "").strip()
    if not url or url in seen:
      continue
    seen.add(url)
    urls.append(url)
  return urls


async def plan_queries(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
  *,
  prompt: str,
  max_queries: int,
  temperature: float = 0.2,
) -> list[str]:
  class QueryPlan(BaseModel):
    queries: list[str] = Field(
      description="Focused web search queries, ordered by usefulness.",
      min_length=1,
      max_length=max_queries,
    )

  intermediate = cheap_llm(llm)
  result = await intermediate.chat_completion(
    prompt=prompt,
    conversation=chat,
    message=message,
    schema=QueryPlan,
    params={"temperature": temperature},
    resolve=True,
  )

  queries = result.get("queries", []) if isinstance(result, dict) else []
  return dedupe_queries(queries, limit=max_queries)


async def run_searches(
  queries: list[str],
  budget: budget_mod.ResearchBudget,
  brief: brief_mod.ResearchBrief,
  *,
  module_id: str,
  status_prefix: str,
  phase: str = "",
  llm: "llm.LLM | None" = None,
  parallel: bool = True,
) -> None:
  if not queries:
    return

  original_count = len(queries)
  queries = dedupe_queries(queries, limit=original_count)
  if len(queries) < original_count:
    logger.debug(
      "Deduplicated %d identical search queries (%d -> %d)",
      original_count - len(queries),
      original_count,
      len(queries),
    )
  if not queries:
    return

  max_results = max(1, config.TOOLS_SEARCH_MAX_RESULTS.value)
  phase_label = f"{phase}: " if phase else ""
  use_parallel = parallel and len(queries) > 1

  if use_parallel:
    await emit_research_status(
      llm,
      (
        f"{status_prefix}: {phase_label}searching {len(queries)} queries "
        f"(up to {SEARCH_CONCURRENCY} parallel)..."
      ).replace(":: ", ": "),
    )

  budget_lock = asyncio.Lock()

  async def _search_one(query: str) -> dict:
    async with budget_lock:
      if not budget.can_search():
        return {"kind": "exhausted", "query": query}

      budget.record_search()

    try:
      logger.info(f"{phase_label}searching '{query[:80]}'")
      results_text = await fetch.web_search(query, max_results=max_results)
      async with budget_lock:
        results_text = budget.trim_to_remaining(results_text)
      return {"kind": "ok", "query": query, "results_text": results_text}
    except budget_mod.BudgetExceeded as exc:
      logger.warning(f"{module_id}: {exc}")
      return {"kind": "budget_error", "query": query, "error": str(exc)}
    except Exception as exc:
      logger.error(f"{module_id}: search failed for '{query}': {exc}")
      return {"kind": "error", "query": query, "error": str(exc)}

  if use_parallel:
    outcomes = await _gather_with_concurrency(
      [_search_one(query) for query in queries],
      limit=SEARCH_CONCURRENCY,
    )
  else:
    outcomes = [await _search_one(query) for query in queries]

  budget_exhausted = False
  for outcome in outcomes:
    kind = outcome["kind"]
    query = outcome.get("query", "")

    if kind == "exhausted":
      if not budget_exhausted:
        brief.add_note(
          f"{phase_label}search budget exhausted before all queries ran.".lstrip()
        )
        budget_exhausted = True
      continue

    if kind == "budget_error":
      brief.add_note(outcome["error"])
      break

    if kind == "error":
      note = f"Search failed for '{query}': {outcome['error']}"
      brief.add_note(note)
      await emit_research_status(
        llm,
        f"{status_prefix}: search failed for '{query[:60]}'...",
      )
      continue

    results_text = outcome["results_text"]
    brief.add_search_results(query, results_text)
    if fetch.is_search_failure_result(results_text):
      note = f"Search failed for '{query}': {results_text}"
      brief.add_note(note)
      await emit_research_status(
        llm,
        f"{status_prefix}: search unavailable for '{query[:60]}'...",
      )


async def read_urls(
  urls: list[str],
  budget: budget_mod.ResearchBudget,
  brief: brief_mod.ResearchBrief,
  *,
  module_id: str,
  status_prefix: str,
  phase: str = "",
  llm: "llm.LLM | None" = None,
  titles: dict[str, str] | None = None,
  parallel: bool = True,
) -> None:
  if not urls:
    return

  phase_label = f"{phase}: " if phase else ""
  scheduled_urls = []
  for url in urls:
    if not budget.can_read_url():
      break
    scheduled_urls.append(url)

  if not scheduled_urls:
    return

  use_parallel = parallel and len(scheduled_urls) > 1
  if use_parallel:
    await emit_research_status(
      llm,
      (
        f"{status_prefix}: {phase_label}reading {len(scheduled_urls)} sources "
        f"(up to {URL_READ_CONCURRENCY} parallel)..."
      ).replace(":: ", ": "),
    )

  budget_lock = asyncio.Lock()

  async def _read_one(url: str) -> dict:
    async with budget_lock:
      if not budget.can_read_url():
        return {"kind": "exhausted", "url": url}

      budget.record_url_read()
      char_limit = page_read_char_limit(budget)

    try:
      logger.info(f"{phase_label}reading {url}")
      page_text = await fetch.read_url(url, max_chars=char_limit)
      async with budget_lock:
        page_text = budget.trim_to_remaining(page_text)
      return {"kind": "ok", "url": url, "page_text": page_text}
    except budget_mod.BudgetExceeded as exc:
      logger.warning(f"{module_id}: {exc}")
      return {"kind": "budget_error", "url": url, "error": str(exc)}
    except Exception as exc:
      logger.warning(f"{module_id}: read_url failed for {url}: {exc}")
      return {"kind": "error", "url": url, "error": str(exc)}

  if use_parallel:
    outcomes = await _gather_with_concurrency(
      [_read_one(url) for url in scheduled_urls],
      limit=URL_READ_CONCURRENCY,
    )
  else:
    outcomes = [await _read_one(url) for url in scheduled_urls]

  for outcome in outcomes:
    kind = outcome["kind"]
    url = outcome.get("url", "")

    if kind in {"exhausted", "budget_error"}:
      if kind == "budget_error":
        brief.add_note(outcome["error"])
      break

    if kind == "error":
      note = f"Could not read {url}: {outcome['error']}"
      brief.add_note(note)
      await emit_research_status(
        llm,
        f"{status_prefix}: could not read {url[:60]}...",
      )
      continue

    page_text = outcome["page_text"]
    if fetch.is_read_failure_result(page_text):
      brief.add_note(page_text)
      await emit_research_status(
        llm,
        f"{status_prefix}: could not read {url[:60]}...",
      )
      continue

    title = (titles or {}).get(url, "")
    brief.add_page(url, page_text, title=title)


async def gather_one_hop(
  queries: list[str],
  budget: budget_mod.ResearchBudget,
  *,
  module_id: str,
  status_prefix: str,
  llm: "llm.LLM | None" = None,
) -> brief_mod.ResearchBrief:
  """Run all planned searches, then read top search-result URLs (single hop)."""
  brief = brief_mod.ResearchBrief()

  await run_searches(
    queries,
    budget,
    brief,
    module_id=module_id,
    status_prefix=status_prefix,
    llm=llm,
  )

  titles = {
    source.url: source.title
    for source in brief.searches
    if source.url
  }
  urls = [source.url for source in brief.searches if source.url]
  await read_urls(
    urls,
    budget,
    brief,
    module_id=module_id,
    status_prefix=status_prefix,
    llm=llm,
    titles=titles,
  )

  return brief_mod.finalize_brief(brief)