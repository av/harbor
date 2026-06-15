"""Smash-and-grab pre-answer web research for Harbor Boost."""

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

import config
import deliverable
import log
import research.brief as brief_mod
import research.budget as budget_mod
import research.orchestrate as orchestrate
import research.workflow as workflow_mod

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

```bash
harbor boost modules add caveman
harbor config set HARBOR_BOOST_CAVEMAN_MAX_SEARCHES 2
harbor config set HARBOR_BOOST_CAVEMAN_MAX_URL_READS 1
harbor config set HARBOR_BOOST_CAVEMAN_MAX_CHARS 30000
harbor config set HARBOR_BOOST_CAVEMAN_TRIGGER heuristic
harbor config set HARBOR_BOOST_TAVILY_API_KEY <key>
# or
harbor config set HARBOR_BOOST_SEARXNG_URL http://searxng:8080
```

**Workflow presets**

- `research-quick` (`tools`, `caveman`, `final`) — fast smash-and-grab research
- `agent-research` (`tools`, `caveman`, `final`) — tool-enabled research during agentic sessions
- `shipyard` — selective ideation research before deeper `ponytail` and `autocheck`

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
Do not repeat near-duplicate queries.
</instruction>

<conversation>
{conversation}
</conversation>

<latest_user_message>
{message}
</latest_user_message>
""".strip()

STATUS_PREFIX = "Caveman research"

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


def should_skip_research(chat: "ch.Chat") -> bool:
  """Pass through without web research on low-value follow-up turns."""
  text = orchestrate.last_user_text(chat)
  if not text or len(text) < 4:
    return True
  if deliverable.is_acknowledgment(text):
    return True
  if orchestrate.CONTINUATION_RE.search(text) and len(text) < 120:
    return True
  if deliverable.is_coding_deliverable(chat) and not deliverable.has_research_signals(text):
    return True
  return False


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


async def needs_research(chat: "ch.Chat", llm: "llm.LLM") -> bool:
  """Return True when this turn should run smash-and-grab web research."""
  if should_skip_research(chat):
    return False
  if getattr(llm, "module", None) == ID_PREFIX:
    return True

  text = orchestrate.last_user_text(chat)
  if _uses_llm_trigger():
    return await classify_needs_research(chat, llm, text)
  return research_heuristic(text)


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


async def apply(chat: "ch.Chat", llm: "llm.LLM", config: dict | None = None):
  message = orchestrate.last_user_text(chat)
  if not message:
    logger.warning(f"{ID_PREFIX}: No user message found, passing through")
    return await workflow_mod.complete_or_defer(llm, config)

  if not await needs_research(chat, llm):
    logger.debug(f"{ID_PREFIX}: Skipping research for: {message[:80]}...")
    return await workflow_mod.complete_or_defer(llm, config)

  await llm.emit_status(f"{STATUS_PREFIX}: planning queries...")
  budget = budget_mod.budget_from_config(ID_PREFIX)

  try:
    queries = await extract_search_queries(chat, llm, message)
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: query extraction failed: {exc}")
    brief = brief_mod.ResearchBrief(query=message)
    brief.add_note(f"Query extraction failed: {exc}")
    brief = brief_mod.finalize_brief(brief)
    await llm.emit_status(f"{STATUS_PREFIX}: query planning failed, continuing without live data...")
    chat.system(brief_mod.render_to_system(brief))
    return await workflow_mod.complete_or_defer(llm, config)

  if not queries:
    logger.warning(f"{ID_PREFIX}: No queries extracted, passing through")
    return await workflow_mod.complete_or_defer(llm, config)

  await llm.emit_status(
    f"{STATUS_PREFIX}: {len(queries)} quer{'y' if len(queries) == 1 else 'ies'}..."
  )
  brief = await gather_research(queries, budget, llm)
  if not brief.query:
    brief.query = message

  if not brief_mod.has_usable_research(brief):
    await llm.emit_status(f"{STATUS_PREFIX}: research unavailable, continuing without live data...")

  chat.system(brief_mod.render_to_system(brief))
  await workflow_mod.complete_or_defer(llm, config)