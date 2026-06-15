"""Deep two-hop pre-answer web research for Harbor Boost."""

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

import config as boost_config
import deliverable
import log
import research.brief as brief_mod
import research.budget as budget_mod
import research.orchestrate as orchestrate
import research.workflow as workflow_mod

if TYPE_CHECKING:
  import chat as ch
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

- `max_queries` — maximum search queries planned per request. Default: `5`
- `max_searches` — maximum web searches per request. Default: `4`
- `max_url_reads` — maximum full-page URL reads per request. Default: `3`
- `max_chars` — maximum research content characters retained. Default: `60000`
- `early_exit_chars` — skip hop 2 when hop 1 gathers this many characters. Default: `15000` (`0` disables)
- `synthesis_max_chars` — cap gathered research passed to brief synthesis. Default: `8000` (`0` disables)
- `trigger` — deep-research gate: `heuristic` (default) or `llm` (cheap yes/no classifier)
- `cache_brief` — *(experimental)* reuse the last research brief when the same user
  question appears again within a request session. Default: `false`

```bash
harbor boost modules add ponytail
harbor config set HARBOR_BOOST_PONYTAIL_MAX_QUERIES 5
harbor config set HARBOR_BOOST_PONYTAIL_MAX_SEARCHES 4
harbor config set HARBOR_BOOST_PONYTAIL_MAX_URL_READS 3
harbor config set HARBOR_BOOST_PONYTAIL_MAX_CHARS 60000
harbor config set HARBOR_BOOST_PONYTAIL_EARLY_EXIT_CHARS 15000
harbor config set HARBOR_BOOST_PONYTAIL_SYNTHESIS_MAX_CHARS 8000
harbor config set HARBOR_BOOST_PONYTAIL_TRIGGER heuristic
harbor config set HARBOR_BOOST_PONYTAIL_CACHE_BRIEF false
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
Synthesize the research into a scannable brief for a coding agent that will implement
or answer the user.

Output rules:
- facts: 3-8 bullets, max ~12 words each. One claim per bullet; no sub-bullets or prose.
  Lead with the claim. Wrap version numbers, API names, and release dates in backticks
  (e.g. `FastAPI 0.115`, `Stripe 2024-06-20`, `Python 3.12`).
- uncertainties: 0-5 bullets framed as verification actions (e.g. "Verify X in official
  docs before migrating Y"). State what to check and why it blocks progress.
- recommendation: One sentence in imperative voice — the first action the agent should take.
- do_not_assume: 2-6 bullets. Each must start with "Do not assume". List unverified
  defaults, compatibility claims, or timelines not proven by the research.

Only include claims supported by the research. Leave lists empty when nothing applies.
</instruction>

<user_question>
{message}
</user_question>

<research_summary>
{research_summary}
</research_summary>
""".strip()

STATUS_PREFIX = "Ponytail research"
BRIEF_CACHE_KEY = "ponytail_brief_cache"


def format_skipped_status(gate_reason: str) -> str:
  """Short status line for emit_status when ponytail passes through."""
  return workflow_mod.format_skipped_status(STATUS_PREFIX, gate_reason)


def format_hop_query_status(hop: int, query_count: int) -> str:
  """Status line before a research hop, matching caveman parenthesized query-count style."""
  noun = "query" if query_count == 1 else "queries"
  return f"{STATUS_PREFIX}: hop {hop} ({query_count} {noun})..."


def format_hop_gathered_status(
  *,
  hop: int,
  query_count: int,
  pages_read: int,
) -> str:
  """Status line after a hop completes with query and URL-read counts."""
  query_noun = "query" if query_count == 1 else "queries"
  url_noun = "URL" if pages_read == 1 else "URLs"
  return (
    f"{STATUS_PREFIX}: hop {hop}, {query_count} {query_noun}, "
    f"read {pages_read} {url_noun}..."
  )


def format_early_exit_status(
  *,
  gathered_chars: int,
  threshold: int,
) -> str:
  """Status line when hop 1 gathered enough content to skip hop 2."""
  return (
    f"{STATUS_PREFIX}: early exit (hop 1 gathered {gathered_chars} chars, "
    f"threshold {threshold}), skipping hop 2..."
  )

TRIGGER_CLASSIFIER_PROMPT = """
<instruction>
Does this question need deep two-hop web research to answer accurately?
Answer yes for migrations, version comparisons, breaking changes, API contract or
endpoint behavior questions, compatibility checks, or multi-source verification that
benefits from a targeted second search pass.
Answer no for simple fact lookups, pure implementation edits, acknowledgments, or
questions answerable from the conversation alone without migration/API-depth research.
</instruction>

<conversation>
{conversation}
</conversation>

<latest_user_message>
{message}
</latest_user_message>
""".strip()


class DeepResearchTriggerDecision(BaseModel):
  needs_deep_research: bool = Field(
    description="True when the latest user message needs deep two-hop web research.",
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
    description=(
      "Short verified claims (max ~12 words each). One fact per bullet. "
      "Wrap version numbers, API names, and dates in backticks."
    ),
    default_factory=list,
  )
  uncertainties: list[str] = Field(
    description=(
      "Actionable verification steps for unresolved gaps "
      "(e.g. 'Verify X in docs before changing Y')."
    ),
    default_factory=list,
  )
  recommendation: str = Field(
    description="One imperative sentence: the first action the coding agent should take.",
    default="",
  )
  do_not_assume: list[str] = Field(
    description=(
      "Unverified assumptions; each bullet starts with 'Do not assume'."
    ),
    default_factory=list,
  )


def is_research_heavy(text: str) -> bool:
  text = (text or "").strip()
  if not text:
    return False
  if RESEARCH_HEAVY_RE.search(text):
    return True
  if "?" in text and deliverable.has_research_signals(text) and len(text) > 30:
    return bool(
      re.search(r"\b(?:migrat|version|api|endpoint|deprecat|compat|upgrade|compare)\b", text, re.I)
    )
  return False


research_skip_reason = orchestrate.research_skip_reason


def should_skip_research(chat: "ch.Chat") -> bool:
  """Pass through without web research on low-value follow-up turns."""
  return research_skip_reason(chat) is not None


def _needs_research_with_module_prefix(chat: "ch.Chat", text: str) -> bool:
  if deliverable.is_implementation_turn(chat):
    return False
  return deliverable.has_research_signals(text) and len(text) >= 20


async def classify_needs_deep_research(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
) -> bool:
  """Cheap yes/no LLM gate for whether deep two-hop research is needed."""
  if not message:
    return False

  intermediate = orchestrate.cheap_llm(llm)
  try:
    result = await intermediate.chat_completion(
      prompt=TRIGGER_CLASSIFIER_PROMPT,
      conversation=chat,
      message=message,
      schema=DeepResearchTriggerDecision,
      params={"temperature": 0},
      resolve=True,
    )
    if isinstance(result, dict):
      return bool(result.get("needs_deep_research"))
  except Exception as exc:
    logger.warning(
      f"{ID_PREFIX}: trigger classifier failed, falling back to heuristic: {exc}"
    )

  return is_research_heavy(message)


async def research_gate_reason(chat: "ch.Chat", llm: "llm.LLM") -> tuple[str, int]:
  """Return pass-through reason or ``triggered``, plus cheap-LLM classifier calls."""
  skip = research_skip_reason(chat)
  if skip:
    return skip, 0

  text = orchestrate.last_user_text(chat)
  if getattr(llm, "module", None) == ID_PREFIX:
    if _needs_research_with_module_prefix(chat, text):
      return "triggered", 0
    return "module_prefix_no_research_signals", 0

  if orchestrate.uses_llm_trigger(boost_config.PONYTAIL_TRIGGER.value):
    if await classify_needs_deep_research(chat, llm, text):
      return "triggered", 1
    return "llm_classifier_no", 1

  if is_research_heavy(text):
    return "triggered", 0
  return "not_research_heavy", 0


async def needs_research(chat: "ch.Chat", llm: "llm.LLM") -> bool:
  """Return True when this turn should run deep two-hop web research."""
  gate_reason, _ = await research_gate_reason(chat, llm)
  return gate_reason == "triggered"


async def plan_search_queries(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
) -> list[str]:
  return await orchestrate.plan_queries(
    chat,
    llm,
    message,
    prompt=QUERY_PLAN_PROMPT,
    max_queries=boost_config.PONYTAIL_MAX_QUERIES.value,
  )


def _first_hop_search_limit(budget: budget_mod.ResearchBudget) -> int:
  if budget.max_searches <= 1:
    return budget.max_searches
  return max(1, budget.max_searches // 2)


async def detect_gaps(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
  brief: brief_mod.ResearchBrief,
) -> GapAnalysis:
  intermediate = orchestrate.cheap_llm(llm)
  result = await intermediate.chat_completion(
    prompt=GAP_DETECTION_PROMPT,
    message=message,
    research_summary=brief_mod.render_to_system(brief),
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
  intermediate = orchestrate.cheap_llm(llm)
  result = await intermediate.chat_completion(
    prompt=SYNTHESIS_PROMPT,
    message=message,
    research_summary=brief_mod.render_for_synthesis(
      brief,
      max_chars=boost_config.PONYTAIL_SYNTHESIS_MAX_CHARS.value,
    ),
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
) -> tuple[brief_mod.ResearchBrief, int]:
  brief = brief_mod.ResearchBrief(query=message)
  extra_calls = 0

  first_queries = initial_queries[:_first_hop_search_limit(budget)]
  await llm.emit_status(format_hop_query_status(1, len(first_queries)))
  searches_before_hop1 = len(brief.searches)
  pages_before_hop1 = len(brief.pages)
  await orchestrate.run_searches(
    first_queries,
    budget,
    brief,
    module_id=ID_PREFIX,
    status_prefix=STATUS_PREFIX,
    phase="Ponytail hop 1",
    llm=llm,
  )

  first_urls = orchestrate.urls_from_brief(brief)[: max(1, budget.max_url_reads // 2 or 1)]
  await orchestrate.read_urls(
    first_urls,
    budget,
    brief,
    module_id=ID_PREFIX,
    status_prefix=STATUS_PREFIX,
    phase="Ponytail hop 1",
    llm=llm,
  )
  hop1_queries = len(brief.searches) - searches_before_hop1
  hop1_pages = len(brief.pages) - pages_before_hop1
  await llm.emit_status(
    format_hop_gathered_status(
      hop=1,
      query_count=hop1_queries,
      pages_read=hop1_pages,
    )
  )

  early_exit_chars = boost_config.PONYTAIL_EARLY_EXIT_CHARS.value
  gathered_chars = orchestrate.content_chars_in_brief(brief)
  if early_exit_chars > 0 and gathered_chars >= early_exit_chars:
    brief.add_note(
      "Early exit: first research hop gathered "
      f"{gathered_chars} chars (threshold {early_exit_chars}); skipping second hop."
    )
    await llm.emit_status(
      format_early_exit_status(
        gathered_chars=gathered_chars,
        threshold=early_exit_chars,
      )
    )
    await llm.emit_status(f"{STATUS_PREFIX}: synthesizing brief...")
    brief = brief_mod.finalize_brief(brief)
    extra_calls += 1
    return await synthesize_brief(chat, llm, message, brief), extra_calls

  await llm.emit_status(f"{STATUS_PREFIX}: detecting gaps...")
  gap = await detect_gaps(chat, llm, message, brief)
  extra_calls += 1
  for gap_note in gap.gaps:
    brief.add_note(f"Gap: {gap_note}")

  follow_up_queries = orchestrate.dedupe_queries(gap.follow_up_queries, limit=3)
  if follow_up_queries and budget.can_search():
    await llm.emit_status(format_hop_query_status(2, len(follow_up_queries)))
    searches_before_hop2 = len(brief.searches)
    pages_before_hop2 = len(brief.pages)
    await orchestrate.run_searches(
      follow_up_queries,
      budget,
      brief,
      module_id=ID_PREFIX,
      status_prefix=STATUS_PREFIX,
      phase="Ponytail hop 2",
      llm=llm,
    )

    new_urls = [
      url for url in orchestrate.urls_from_brief(brief)
      if url not in first_urls
    ]
    await orchestrate.read_urls(
      new_urls,
      budget,
      brief,
      module_id=ID_PREFIX,
      status_prefix=STATUS_PREFIX,
      phase="Ponytail hop 2",
      llm=llm,
    )
    hop2_queries = len(brief.searches) - searches_before_hop2
    hop2_pages = len(brief.pages) - pages_before_hop2
    await llm.emit_status(
      format_hop_gathered_status(
        hop=2,
        query_count=hop2_queries,
        pages_read=hop2_pages,
      )
    )
  elif follow_up_queries:
    brief.add_note("Second research hop skipped: search budget exhausted.")

  await llm.emit_status(f"{STATUS_PREFIX}: synthesizing brief...")
  brief = brief_mod.finalize_brief(brief)
  extra_calls += 1
  return await synthesize_brief(chat, llm, message, brief), extra_calls


async def _execute_research(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
  queries: list[str],
  budget: budget_mod.ResearchBudget,
) -> tuple[brief_mod.ResearchBrief, int]:
  try:
    return await run_research_loop(chat, llm, message, queries, budget)
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: research loop failed: {exc}")
    brief = workflow_mod.failure_brief(message, f"Research loop failed: {exc}")
    await llm.emit_status(f"{STATUS_PREFIX}: research loop failed, continuing without live data...")
    return brief, 0


async def apply(chat: "ch.Chat", llm: "llm.LLM", config: dict | None = None):
  await workflow_mod.apply_research_module(
    chat,
    llm,
    config,
    module_id=ID_PREFIX,
    logger=logger,
    status_prefix=STATUS_PREFIX,
    brief_cache_key=BRIEF_CACHE_KEY,
    cache_brief_enabled=boost_config.PONYTAIL_CACHE_BRIEF.value,
    format_skipped=format_skipped_status,
    research_gate_reason=research_gate_reason,
    plan_queries=plan_search_queries,
    execute_research=_execute_research,
    no_queries_reason="no_queries_planned",
    no_queries_log="No queries planned, passing through",
    query_failure_log="query planning failed",
    query_failure_note_label="Query planning",
    query_failure_status="query planning failed, continuing without live data...",
    query_failure_metric_key="query_planning_failed",
  )