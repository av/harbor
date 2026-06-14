"""Shared research orchestration for agentic Boost modules."""

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

import config
import log
import research.brief as brief_mod
import research.budget as budget_mod
import research.fetch as fetch

if TYPE_CHECKING:
  import chat as ch
  import llm

logger = log.setup_logger(__name__)

CONTINUATION_RE = re.compile(
  r"\b(?:continue|keep\s+going|go\s+on|proceed|carry\s+on|as\s+planned|same\s+as\s+before)\b",
  re.IGNORECASE,
)


def last_user_text(chat: "ch.Chat") -> str:
  node = chat.match_one(role="user", index=-1)
  return (node.content or "").strip() if node else ""


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
) -> None:
  max_results = max(1, config.TOOLS_SEARCH_MAX_RESULTS.value)
  phase_label = f"{phase}: " if phase else ""

  for query in queries:
    if not budget.can_search():
      brief.add_note(f"{phase_label}search budget exhausted before all queries ran.".lstrip())
      break

    try:
      budget.record_search()
      logger.info(f"{phase_label}searching '{query[:80]}'")
      results_text = await fetch.web_search(query, max_results=max_results)
      results_text = budget.trim_to_remaining(results_text)
      brief.add_search_results(query, results_text)
      if fetch.is_search_failure_result(results_text):
        note = f"Search failed for '{query}': {results_text}"
        brief.add_note(note)
        await emit_research_status(
          llm,
          f"{status_prefix}: search unavailable for '{query[:60]}'...",
        )
    except budget_mod.BudgetExceeded as exc:
      logger.warning(f"{module_id}: {exc}")
      brief.add_note(str(exc))
      break
    except Exception as exc:
      logger.error(f"{module_id}: search failed for '{query}': {exc}")
      note = f"Search failed for '{query}': {exc}"
      brief.add_note(note)
      await emit_research_status(
        llm,
        f"{status_prefix}: search failed for '{query[:60]}'...",
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
) -> None:
  phase_label = f"{phase}: " if phase else ""

  for url in urls:
    if not budget.can_read_url():
      break

    try:
      budget.record_url_read()
      logger.info(f"{phase_label}reading {url}")
      page_text = await fetch.read_url(
        url,
        max_chars=page_read_char_limit(budget),
      )
      page_text = budget.trim_to_remaining(page_text)
      if fetch.is_read_failure_result(page_text):
        brief.add_note(page_text)
        await emit_research_status(
          llm,
          f"{status_prefix}: could not read {url[:60]}...",
        )
        continue

      title = (titles or {}).get(url, "")
      brief.add_page(url, page_text, title=title)
    except budget_mod.BudgetExceeded as exc:
      logger.warning(f"{module_id}: {exc}")
      brief.add_note(str(exc))
      break
    except Exception as exc:
      logger.warning(f"{module_id}: read_url failed for {url}: {exc}")
      note = f"Could not read {url}: {exc}"
      brief.add_note(note)
      await emit_research_status(
        llm,
        f"{status_prefix}: could not read {url[:60]}...",
      )


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