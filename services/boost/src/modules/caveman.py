"""Smash-and-grab pre-answer web research for Harbor Boost."""

import hashlib
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

import config
import deliverable
import log
from modules import keel
import research.brief as brief_mod
import research.budget as budget_mod
import research.debug_metrics as debug_metrics
import research.orchestrate as orchestrate
import research.workflow as workflow_mod
from state import request as request_state

if TYPE_CHECKING:
  import chat as ch
  import llm

ID_PREFIX = "caveman"

DOCS = """
`caveman` performs fast, budget-capped web research before the final answer.
On research turns it extracts 1-3 search queries with a cheap internal LLM call,
runs `web_search` directly (not via model tool calls), optionally reads top hit
pages, injects a compact `<research_brief>` system block, then streams the
downstream completion.

Pass-through turns (implementation edits, acknowledgments, short "continue"
messages) skip research to keep latency low.

**When to use**

- Quick fact-finding before answering — API docs, release notes, error lookups
- Default research module when latency matters more than depth
- Prefer over `ponytail` for ideation passes and routine lookups
- Pair with `tools` so the model can search again during the final completion

**Parameters**

- `max_searches` — maximum web searches per request. Default: `2`
- `max_url_reads` — maximum full-page URL reads per request. Default: `1`
- `max_chars` — maximum research content characters retained. Default: `30000`
- `trigger` — research gate: `heuristic` (default) or `llm` (cheap yes/no classifier)
- `cache_brief` — *(experimental)* reuse the last research brief when the same user
  question appears again within a request session. Default: `false`

```bash
harbor boost modules add caveman
harbor config set HARBOR_BOOST_CAVEMAN_MAX_SEARCHES 2
harbor config set HARBOR_BOOST_CAVEMAN_MAX_URL_READS 1
harbor config set HARBOR_BOOST_CAVEMAN_MAX_CHARS 30000
harbor config set HARBOR_BOOST_CAVEMAN_TRIGGER heuristic
harbor config set HARBOR_BOOST_CAVEMAN_CACHE_BRIEF false
harbor config set HARBOR_BOOST_TAVILY_API_KEY <key>
# or
harbor config set HARBOR_BOOST_SEARXNG_URL http://searxng:8080
```

**Workflow presets**

- `research-quick` (`tools`, `caveman`, `final`) — fast smash-and-grab research
- `agent-research` (`tools`, `caveman`, `final`) — tool-enabled research during agentic sessions
- `shipyard` — selective ideation research before deeper `ponytail` and `autocheck`;
  skips when a keel implementation brief is already anchored

**Standalone**

```bash
docker run \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \\
  -e "HARBOR_BOOST_MODULES=caveman" \\
  -e "HARBOR_BOOST_SEARXNG_URL=http://host.docker.internal:33811" \\
  -p 8004:8000 \\
  ghcr.io/av/harbor-boost:latest
```
"""

logger = log.setup_logger(ID_PREFIX)

QUERY_EXTRACTION_PROMPT = """
<instruction>
Extract 1-3 concise web search queries that would help answer the user's latest message.
Use absolute dates for time-sensitive topics. Prefer specific product, API, or error terms.
When the user quotes an error message or stack trace, include the exact error string in at
least one query (wrap the error text in double quotes).
When the user mentions version numbers (e.g. Python 3.12, FastAPI 0.115), carry those
versions into relevant queries.
Prefer official documentation: use site:docs.* when a docs domain is known, or
"<package> docs" / "<product> documentation" as the first query when applicable.
Do not repeat near-duplicate queries. Return at most 3 queries.
</instruction>

<conversation>
{conversation}
</conversation>

<latest_user_message>
{message}
</latest_user_message>
""".strip()

STATUS_PREFIX = "Caveman research"
BRIEF_CACHE_KEY = "caveman_brief_cache"


def format_skipped_status(gate_reason: str) -> str:
  """Short status line for emit_status when caveman passes through."""
  reason = (gate_reason or "unknown").strip()
  return f"{STATUS_PREFIX}: skipped ({reason})"


def format_query_status(query_count: int) -> str:
  """Status line before one-hop research, matching ponytail query-count style."""
  noun = "query" if query_count == 1 else "queries"
  return f"{STATUS_PREFIX}: ({query_count} {noun})..."


def format_gathered_status(
  *,
  query_count: int,
  pages_read: int,
) -> str:
  """Status line after gather completes with query and URL-read counts."""
  query_noun = "query" if query_count == 1 else "queries"
  url_noun = "URL" if pages_read == 1 else "URLs"
  return (
    f"{STATUS_PREFIX}: {query_count} {query_noun}, "
    f"read {pages_read} {url_noun}..."
  )

TRIGGER_CLASSIFIER_PROMPT = """
<instruction>
Does this question need external web research to answer accurately?
Answer yes for API docs, release notes, version facts, error lookups, or other live facts.
Answer no for pure implementation edits, acknowledgments, or questions answerable from the conversation alone.
</instruction>

<conversation>
{conversation}
</conversation>

<latest_user_message>
{message}
</latest_user_message>
""".strip()


class ResearchTriggerDecision(BaseModel):
  needs_external_research: bool = Field(
    description="True when the latest user message needs external web research.",
  )


def _uses_llm_trigger() -> bool:
  return (config.CAVEMAN_TRIGGER.value or "heuristic").strip().lower() == "llm"


def _question_hash(text: str) -> str:
  return hashlib.sha256((text or "").strip().encode()).hexdigest()


def _request_store(name: str, default):
  request = request_state.get()
  if request is None:
    return default

  if not hasattr(request.state, name):
    setattr(request.state, name, default)

  return getattr(request.state, name)


def _get_cached_brief(message: str) -> brief_mod.ResearchBrief | None:
  if not config.CAVEMAN_CACHE_BRIEF.value:
    return None

  cached = _request_store(BRIEF_CACHE_KEY, None)
  if not isinstance(cached, tuple) or len(cached) != 2:
    return None

  cached_hash, cached_brief = cached
  if cached_hash != _question_hash(message):
    return None
  if not isinstance(cached_brief, brief_mod.ResearchBrief):
    return None

  return cached_brief.model_copy(deep=True)


def _store_cached_brief(message: str, brief: brief_mod.ResearchBrief) -> None:
  if not config.CAVEMAN_CACHE_BRIEF.value:
    return

  request = request_state.get()
  if request is None:
    return

  setattr(
    request.state,
    BRIEF_CACHE_KEY,
    (_question_hash(message), brief.model_copy(deep=True)),
  )


def research_skip_reason(chat: "ch.Chat") -> str | None:
  """Return a pass-through reason when research should be skipped, else None."""
  low_value = orchestrate.low_value_skip_reason(chat)
  if low_value:
    return low_value

  text = orchestrate.last_user_text(chat)
  if deliverable.is_coding_deliverable(chat) and not deliverable.has_research_signals(text):
    return "coding_no_research_signals"

  brief = keel.get_stored_brief() or keel.hydrate_brief_from_chat(chat)
  if (
    brief
    and keel.is_implementation_brief(brief)
    and deliverable.is_coding_deliverable(chat)
  ):
    return "keel_implementation_brief"

  return None


def should_skip_research(chat: "ch.Chat") -> bool:
  """Pass through without web research on low-value follow-up turns."""
  return research_skip_reason(chat) is not None


async def classify_needs_research(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
) -> bool:
  """Cheap yes/no LLM gate for whether external web research is needed."""
  if not message:
    return False

  intermediate = orchestrate.cheap_llm(llm)
  try:
    result = await intermediate.chat_completion(
      prompt=TRIGGER_CLASSIFIER_PROMPT,
      conversation=chat,
      message=message,
      schema=ResearchTriggerDecision,
      params={"temperature": 0},
      resolve=True,
    )
    if isinstance(result, dict):
      return bool(result.get("needs_external_research"))
  except Exception as exc:
    logger.warning(
      f"{ID_PREFIX}: trigger classifier failed, falling back to heuristic: {exc}"
    )

  return research_heuristic(message)


async def research_gate_reason(chat: "ch.Chat", llm: "llm.LLM") -> str:
  """Return ``triggered`` when research should run, else a pass-through reason."""
  skip = research_skip_reason(chat)
  if skip:
    return skip

  text = orchestrate.last_user_text(chat)
  if getattr(llm, "module", None) == ID_PREFIX:
    return "triggered"

  if _uses_llm_trigger():
    if await classify_needs_research(chat, llm, text):
      return "triggered"
    return "llm_classifier_no"

  if research_heuristic(text):
    return "triggered"
  return "heuristic_no_match"


async def needs_research(chat: "ch.Chat", llm: "llm.LLM") -> bool:
  """Return True when this turn should run smash-and-grab web research."""
  return await research_gate_reason(chat, llm) == "triggered"


def research_heuristic(text: str) -> bool:
  text = (text or "").strip()
  if not text or len(text) < 8:
    return False
  if deliverable.has_research_signals(text):
    return True
  return "?" in text and len(text) > 20


async def extract_search_queries(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
) -> list[str]:
  return await orchestrate.plan_queries(
    chat,
    llm,
    message,
    prompt=QUERY_EXTRACTION_PROMPT,
    max_queries=3,
  )


async def gather_research(
  queries: list[str],
  budget: budget_mod.ResearchBudget,
  llm: "llm.LLM | None" = None,
) -> brief_mod.ResearchBrief:
  return await orchestrate.gather_one_hop(
    queries,
    budget,
    module_id=ID_PREFIX,
    status_prefix=STATUS_PREFIX,
    llm=llm,
  )


def _record_debug(
  payload: debug_metrics.ModuleDebug,
  *,
  gate_reason: str | None = None,
) -> None:
  debug_metrics.record(ID_PREFIX, payload)
  if gate_reason is not None:
    logger.debug(
      f"{ID_PREFIX}: Pass-through — {gate_reason} ({payload.model_dump()})"
    )
  else:
    logger.debug(f"{ID_PREFIX}: {payload.model_dump()}")


async def apply(chat: "ch.Chat", llm: "llm.LLM", config: dict | None = None):
  timer = debug_metrics.DebugTimer()
  extra_calls = 0
  message = orchestrate.last_user_text(chat)
  if not message:
    logger.warning(f"{ID_PREFIX}: No user message found, passing through")
    await llm.emit_status(format_skipped_status("empty_message"))
    _record_debug(
      debug_metrics.skipped_payload("empty_message", duration_ms=timer.elapsed_ms()),
    )
    return await workflow_mod.complete_or_defer(llm, config)

  gate_reason = await research_gate_reason(chat, llm)
  if _uses_llm_trigger():
    extra_calls += 1
  if gate_reason != "triggered":
    await llm.emit_status(format_skipped_status(gate_reason))
    _record_debug(
      debug_metrics.skipped_payload(
        gate_reason,
        duration_ms=timer.elapsed_ms(),
        extra_calls=extra_calls,
      ),
      gate_reason=gate_reason,
    )
    return await workflow_mod.complete_or_defer(llm, config)

  cached_brief = _get_cached_brief(message)
  if cached_brief is not None:
    logger.debug(f"{ID_PREFIX}: Reusing cached brief for same question")
    await llm.emit_status(f"{STATUS_PREFIX}: using cached brief...")
    if not cached_brief.query:
      cached_brief.query = message
    chat.system(brief_mod.render_to_system(cached_brief))
    _record_debug(
      debug_metrics.triggered_payload(
        "triggered",
        duration_ms=timer.elapsed_ms(),
        extra_calls=extra_calls,
        cached_brief=True,
      ),
    )
    return await workflow_mod.complete_or_defer(llm, config)

  await llm.emit_status(f"{STATUS_PREFIX}: planning queries...")
  budget = budget_mod.budget_from_config(ID_PREFIX)

  try:
    queries = await extract_search_queries(chat, llm, message)
    extra_calls += 1
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: query extraction failed: {exc}")
    brief = workflow_mod.failure_brief(message, f"Query extraction failed: {exc}")
    await llm.emit_status(f"{STATUS_PREFIX}: query planning failed, continuing without live data...")
    chat.system(brief_mod.render_to_system(brief))
    _record_debug(
      debug_metrics.triggered_payload(
        "triggered",
        duration_ms=timer.elapsed_ms(),
        extra_calls=extra_calls,
        query_extraction_failed=True,
      ),
    )
    return await workflow_mod.complete_or_defer(llm, config)

  if not queries:
    logger.warning(f"{ID_PREFIX}: No queries extracted, passing through")
    await llm.emit_status(format_skipped_status("no_queries_extracted"))
    _record_debug(
      debug_metrics.triggered_payload(
        "no_queries_extracted",
        duration_ms=timer.elapsed_ms(),
        extra_calls=extra_calls,
      ),
    )
    return await workflow_mod.complete_or_defer(llm, config)

  await llm.emit_status(format_query_status(len(queries)))
  brief = await gather_research(queries, budget, llm)
  await llm.emit_status(
    format_gathered_status(
      query_count=len(queries),
      pages_read=len(brief.pages),
    )
  )
  if not brief.query:
    brief.query = message

  if not brief_mod.has_usable_research(brief):
    await llm.emit_status(f"{STATUS_PREFIX}: research unavailable, continuing without live data...")

  _store_cached_brief(message, brief)
  chat.system(brief_mod.render_to_system(brief))
  _record_debug(
    debug_metrics.triggered_payload(
      "triggered",
      duration_ms=timer.elapsed_ms(),
      extra_calls=extra_calls,
      queries=len(queries),
      searches=len(brief.searches),
      pages=len(brief.pages),
    ),
  )
  await workflow_mod.complete_or_defer(llm, config)