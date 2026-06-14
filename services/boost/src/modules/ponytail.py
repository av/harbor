"""Deep two-hop pre-answer web research for Harbor Boost."""

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

import chat as ch
import config
import deliverable
import log
import research.brief as brief_mod
import research.budget as budget_mod
import research.fetch as fetch
import research.workflow as workflow_mod

if TYPE_CHECKING:
  import llm

ID_PREFIX = "ponytail"

DOCS = """
`ponytail` performs deeper, two-hop web research before the final answer.
On research turns it plans search queries, runs an initial search pass, reads
top pages, detects information gaps, runs a targeted second search, then
synthesizes a structured `<research_brief>` with facts, uncertainties,
recommendation, and do-not-assume guidance before streaming the downstream
completion.

Unlike `caveman`, ponytail triggers selectively on research-heavy questions
(migrations, version comparisons, API behavior) and uses higher default budgets.

**When to use**

- Migrations, version comparisons, breaking changes, and API behavior questions
- When the first search pass may miss gaps — ponytail runs a targeted second hop
- Prefer over `caveman` when accuracy matters more than latency (higher budgets)
- Skips implementation-only and acknowledgment turns like `caveman`

**Parameters**

- `max_searches` — maximum web searches per request. Default: `4`
- `max_url_reads` — maximum full-page URL reads per request. Default: `3`
- `max_chars` — maximum research content characters retained. Default: `60000`

```bash
harbor boost modules add ponytail
harbor config set HARBOR_BOOST_PONYTAIL_MAX_SEARCHES 4
harbor config set HARBOR_BOOST_PONYTAIL_MAX_URL_READS 3
harbor config set HARBOR_BOOST_PONYTAIL_MAX_CHARS 60000
harbor config set HARBOR_BOOST_TAVILY_API_KEY <key>
# or
harbor config set HARBOR_BOOST_SEARXNG_URL http://searxng:8080
```

**Workflow presets**

- `research-deep` (`tools`, `ponytail`, `final`) — two-hop research for complex questions
- `shipyard` — deeper implementation research after `caveman` ideation and `tools`

**Standalone**

```bash
docker run \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \\
  -e "HARBOR_BOOST_MODULES=ponytail" \\
  -e "HARBOR_BOOST_SEARXNG_URL=http://host.docker.internal:33811" \\
  -p 8004:8000 \\
  ghcr.io/av/harbor-boost:latest
```
"""

logger = log.setup_logger(ID_PREFIX)

SKIP_MESSAGE_RE = re.compile(
  r"^\s*(?:"
  r"thanks?(?:\s+you)?|thank\s+you|thx|ok(?:ay)?|cool|great|perfect|sounds?\s+good|"
  r"got\s+it|understood|yes|no|yep|nope|sure|continue|go\s+on|go\s+ahead|"
  r"proceed|keep\s+going|lgtm|looks?\s+good|done|next|ship\s+it"
  r")\s*[.!]?\s*$",
  re.IGNORECASE,
)
CONTINUATION_RE = re.compile(
  r"\b(?:continue|keep\s+going|go\s+on|proceed|carry\s+on|as\s+planned|same\s+as\s+before)\b",
  re.IGNORECASE,
)
RESEARCH_HEAVY_RE = re.compile(
  r"\b(?:"
  r"migrat(?:e|ion|ing)|upgrade(?:\s+path|\s+guide)?|breaking\s+change|"
  r"deprecat(?:e|ed|ion)|compatib(?:le|ility)|changelog|release\s+notes?|"
  r"version\s+compar|compare\s+versions?|versus|vs\.?|semver|"
  r"api\s+(?:behavior|reference|contract|endpoint|spec|version)|"
  r"endpoint\s+behavior|request\s+format|response\s+format|"
  r"from\s+v?\d|to\s+v?\d|v\d+(?:\.\d+)+"
  r")\b",
  re.IGNORECASE,
)
RESEARCH_SIGNAL_RE = re.compile(
  r"\b(?:"
  r"latest|current|today|recent(?:ly)?|20\d{2}|version|release|"
  r"documentat(?:ion|e)|lookup|search\s+for"
  r")\b",
  re.IGNORECASE,
)

QUERY_PLAN_PROMPT = """
<instruction>
Plan 2-4 focused web search queries to answer the user's latest message.
Prioritize official docs, migration guides, changelogs, and version comparisons.
Use absolute dates for time-sensitive topics. Avoid near-duplicate queries.
</instruction>

<conversation>
{conversation}
</conversation>

<latest_user_message>
{message}
</latest_user_message>
""".strip()

GAP_DETECTION_PROMPT = """
<instruction>
Review the gathered research for the user's question. Identify missing facts,
conflicting claims, or areas that still need verification. Propose 1-3 follow-up
search queries only when they would materially improve the answer.
</instruction>

<user_question>
{message}
</user_question>

<research_summary>
{research_summary}
</research_summary>
""".strip()

SYNTHESIS_PROMPT = """
<instruction>
Synthesize the research into a concise brief for the downstream assistant.
List only claims supported by the research. Flag unresolved gaps as uncertainties.
Give one practical recommendation and list assumptions the assistant must not make.
</instruction>

<user_question>
{message}
</user_question>

<research_summary>
{research_summary}
</research_summary>
""".strip()


class SearchQueryPlan(BaseModel):
  queries: list[str] = Field(
    description="Focused web search queries, ordered by usefulness.",
    min_length=1,
    max_length=4,
  )


class GapAnalysis(BaseModel):
  gaps: list[str] = Field(
    description="Missing or uncertain information still needed.",
    default_factory=list,
  )
  follow_up_queries: list[str] = Field(
    description="Targeted follow-up search queries for the second research hop.",
    default_factory=list,
    max_length=3,
  )


class StructuredBrief(BaseModel):
  facts: list[str] = Field(
    description="Verified facts supported by the gathered research.",
    default_factory=list,
  )
  uncertainties: list[str] = Field(
    description="Unresolved gaps, conflicts, or low-confidence claims.",
    default_factory=list,
  )
  recommendation: str = Field(
    description="Practical guidance for answering the user.",
    default="",
  )
  do_not_assume: list[str] = Field(
    description="Assumptions the downstream assistant must avoid.",
    default_factory=list,
  )


def _last_user_text(chat: "ch.Chat") -> str:
  node = chat.match_one(role="user", index=-1)
  return (node.content or "").strip() if node else ""


def is_research_heavy(text: str) -> bool:
  text = (text or "").strip()
  if not text:
    return False
  if RESEARCH_HEAVY_RE.search(text):
    return True
  if "?" in text and RESEARCH_SIGNAL_RE.search(text) and len(text) > 30:
    return bool(
      re.search(r"\b(?:migrat|version|api|endpoint|deprecat|compat|upgrade|compare)\b", text, re.I)
    )
  return False


def has_research_signals(text: str) -> bool:
  text = (text or "").strip()
  if not text:
    return False
  if "?" in text:
    return True
  if re.search(r"https?://", text, re.IGNORECASE):
    return True
  return bool(RESEARCH_SIGNAL_RE.search(text))


def should_skip_research(chat: "ch.Chat") -> bool:
  """Pass through without web research on low-value follow-up turns."""
  text = _last_user_text(chat)
  if not text or len(text) < 4:
    return True
  if SKIP_MESSAGE_RE.match(text):
    return True
  if CONTINUATION_RE.search(text) and len(text) < 120:
    return True
  return False


def needs_research(chat: "ch.Chat", llm: "llm.LLM") -> bool:
  """Return True when this turn should run deep two-hop web research."""
  if should_skip_research(chat):
    return False

  text = _last_user_text(chat)
  if is_research_heavy(text):
    return True

  if getattr(llm, "module", None) == ID_PREFIX:
    if deliverable.is_coding_deliverable(chat) and not has_research_signals(text):
      return False
    return has_research_signals(text) and len(text) >= 20

  return False


def _cheap_llm(llm: "llm.LLM") -> "llm.LLM":
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


def _dedupe_queries(queries: list[str], *, limit: int) -> list[str]:
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


async def plan_search_queries(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
) -> list[str]:
  intermediate = _cheap_llm(llm)
  result = await intermediate.chat_completion(
    prompt=QUERY_PLAN_PROMPT,
    conversation=chat,
    message=message,
    schema=SearchQueryPlan,
    params={"temperature": 0.2},
    resolve=True,
  )

  queries = result.get("queries", []) if isinstance(result, dict) else []
  return _dedupe_queries(queries, limit=4)


def _page_read_char_limit(budget: budget_mod.ResearchBudget) -> int:
  remaining = budget.remaining_chars()
  if budget.max_url_reads <= 0:
    return remaining
  return max(1000, remaining // max(1, budget.max_url_reads))


def _first_hop_search_limit(budget: budget_mod.ResearchBudget) -> int:
  if budget.max_searches <= 1:
    return budget.max_searches
  return max(1, budget.max_searches // 2)


def _urls_from_brief(brief: brief_mod.ResearchBrief) -> list[str]:
  urls = []
  seen = set()
  for source in [*brief.searches, *brief.pages]:
    url = (source.url or "").strip()
    if not url or url in seen:
      continue
    seen.add(url)
    urls.append(url)
  return urls


async def _emit_research_status(llm: "llm.LLM | None", status: str) -> None:
  if llm is not None:
    await llm.emit_status(status)


async def _run_searches(
  queries: list[str],
  budget: budget_mod.ResearchBudget,
  brief: brief_mod.ResearchBrief,
  *,
  phase: str,
  llm: "llm.LLM | None" = None,
) -> None:
  max_results = max(1, config.TOOLS_SEARCH_MAX_RESULTS.value)

  for query in queries:
    if not budget.can_search():
      brief.add_note(f"{phase}: search budget exhausted before all queries ran.")
      break

    try:
      budget.record_search()
      logger.info(f"{phase}: searching '{query[:80]}'")
      results_text = await fetch.web_search(query, max_results=max_results)
      results_text = budget.trim_to_remaining(results_text)
      brief.add_search_results(query, results_text)
      if fetch.is_search_failure_result(results_text):
        note = f"Search failed for '{query}': {results_text}"
        brief.add_note(note)
        await _emit_research_status(
          llm,
          f"Ponytail research: search unavailable for '{query[:60]}'...",
        )
    except budget_mod.BudgetExceeded as exc:
      logger.warning(f"{ID_PREFIX}: {exc}")
      brief.add_note(str(exc))
      break
    except Exception as exc:
      logger.error(f"{ID_PREFIX}: search failed for '{query}': {exc}")
      note = f"Search failed for '{query}': {exc}"
      brief.add_note(note)
      await _emit_research_status(
        llm,
        f"Ponytail research: search failed for '{query[:60]}'...",
      )


async def _read_urls(
  urls: list[str],
  budget: budget_mod.ResearchBudget,
  brief: brief_mod.ResearchBrief,
  *,
  phase: str,
  llm: "llm.LLM | None" = None,
) -> None:
  for url in urls:
    if not budget.can_read_url():
      break

    try:
      budget.record_url_read()
      logger.info(f"{phase}: reading {url}")
      page_text = await fetch.read_url(
        url,
        max_chars=_page_read_char_limit(budget),
      )
      page_text = budget.trim_to_remaining(page_text)
      if fetch.is_read_failure_result(page_text):
        brief.add_note(page_text)
        await _emit_research_status(
          llm,
          f"Ponytail research: could not read {url[:60]}...",
        )
        continue

      brief.add_page(url, page_text)
    except budget_mod.BudgetExceeded as exc:
      logger.warning(f"{ID_PREFIX}: {exc}")
      brief.add_note(str(exc))
      break
    except Exception as exc:
      logger.warning(f"{ID_PREFIX}: read_url failed for {url}: {exc}")
      note = f"Could not read {url}: {exc}"
      brief.add_note(note)
      await _emit_research_status(
        llm,
        f"Ponytail research: could not read {url[:60]}...",
      )


def _render_research_summary(brief: brief_mod.ResearchBrief) -> str:
  return brief_mod.render_to_system(brief)


async def detect_gaps(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
  brief: brief_mod.ResearchBrief,
) -> GapAnalysis:
  intermediate = _cheap_llm(llm)
  result = await intermediate.chat_completion(
    prompt=GAP_DETECTION_PROMPT,
    message=message,
    research_summary=_render_research_summary(brief),
    schema=GapAnalysis,
    params={"temperature": 0.2},
    resolve=True,
  )

  if isinstance(result, dict):
    return GapAnalysis(**result)
  return GapAnalysis()


async def synthesize_brief(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
  brief: brief_mod.ResearchBrief,
) -> brief_mod.ResearchBrief:
  intermediate = _cheap_llm(llm)
  result = await intermediate.chat_completion(
    prompt=SYNTHESIS_PROMPT,
    message=message,
    research_summary=_render_research_summary(brief),
    schema=StructuredBrief,
    params={"temperature": 0.2},
    resolve=True,
  )

  if isinstance(result, dict):
    structured = StructuredBrief(**result)
    brief.facts = [item.strip() for item in structured.facts if item.strip()]
    brief.uncertainties = [item.strip() for item in structured.uncertainties if item.strip()]
    brief.recommendation = (structured.recommendation or "").strip()
    brief.do_not_assume = [item.strip() for item in structured.do_not_assume if item.strip()]

  return brief


async def run_research_loop(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
  initial_queries: list[str],
  budget: budget_mod.ResearchBudget,
) -> brief_mod.ResearchBrief:
  brief = brief_mod.ResearchBrief(query=message)

  await llm.emit_status(
    f"Ponytail research: hop 1 ({len(initial_queries)} quer"
    f"{'y' if len(initial_queries) == 1 else 'ies'})..."
  )
  first_queries = initial_queries[:_first_hop_search_limit(budget)]
  await _run_searches(first_queries, budget, brief, phase="Ponytail hop 1", llm=llm)

  await llm.emit_status("Ponytail research: reading sources...")
  first_urls = _urls_from_brief(brief)[: max(1, budget.max_url_reads // 2 or 1)]
  await _read_urls(first_urls, budget, brief, phase="Ponytail hop 1", llm=llm)

  await llm.emit_status("Ponytail research: detecting gaps...")
  gap = await detect_gaps(chat, llm, message, brief)
  for gap_note in gap.gaps:
    brief.add_note(f"Gap: {gap_note}")

  follow_up_queries = _dedupe_queries(gap.follow_up_queries, limit=3)
  if follow_up_queries and budget.can_search():
    await llm.emit_status("Ponytail research: hop 2 follow-up...")
    await _run_searches(follow_up_queries, budget, brief, phase="Ponytail hop 2", llm=llm)

    new_urls = [
      url for url in _urls_from_brief(brief)
      if url not in first_urls
    ]
    await _read_urls(new_urls, budget, brief, phase="Ponytail hop 2", llm=llm)
  elif follow_up_queries:
    brief.add_note("Second research hop skipped: search budget exhausted.")

  await llm.emit_status("Ponytail research: synthesizing brief...")
  brief = brief_mod.finalize_brief(brief)
  return await synthesize_brief(chat, llm, message, brief)


async def apply(chat: "ch.Chat", llm: "llm.LLM", config: dict | None = None):
  message = _last_user_text(chat)
  if not message:
    logger.warning(f"{ID_PREFIX}: No user message found, passing through")
    return await workflow_mod.complete_or_defer(llm, config)

  if not needs_research(chat, llm):
    logger.debug(f"{ID_PREFIX}: Skipping research for: {message[:80]}...")
    return await workflow_mod.complete_or_defer(llm, config)

  await llm.emit_status("Ponytail research: planning queries...")
  budget = budget_mod.budget_from_config(ID_PREFIX)

  try:
    queries = await plan_search_queries(chat, llm, message)
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: query planning failed: {exc}")
    brief = brief_mod.ResearchBrief(query=message)
    brief.add_note(f"Query planning failed: {exc}")
    brief = brief_mod.finalize_brief(brief)
    await llm.emit_status("Ponytail research: query planning failed, continuing without live data...")
    chat.system(brief_mod.render_to_system(brief))
    return await workflow_mod.complete_or_defer(llm, config)

  if not queries:
    logger.warning(f"{ID_PREFIX}: No queries planned, passing through")
    return await workflow_mod.complete_or_defer(llm, config)

  try:
    brief = await run_research_loop(chat, llm, message, queries, budget)
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: research loop failed: {exc}")
    brief = brief_mod.ResearchBrief(query=message)
    brief.add_note(f"Research loop failed: {exc}")
    brief = brief_mod.finalize_brief(brief)
    await llm.emit_status("Ponytail research: research loop failed, continuing without live data...")

  if not brief.query:
    brief.query = message

  if not brief_mod.has_usable_research(brief):
    await llm.emit_status("Ponytail research: research unavailable, continuing without live data...")

  chat.system(brief_mod.render_to_system(brief))
  await workflow_mod.complete_or_defer(llm, config)