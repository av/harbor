"""Smash-and-grab pre-answer web research for Harbor Boost."""

from typing import TYPE_CHECKING

import config as boost_config
import deliverable
import log
import research.brief as brief_mod
import research.budget as budget_mod
import research.orchestrate as orchestrate
import research.workflow as workflow_mod
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import chat as ch
    import llm

ID_PREFIX = "quickhop"

DOCS = """
`quickhop` performs fast, budget-capped web research before the final answer.
On research turns it extracts 1-3 search queries with a cheap internal LLM call,
runs `web_search` directly (not via model tool calls), optionally reads top hit
pages, injects a compact `<research_brief>` system block, then streams the
downstream completion.

Pass-through turns (implementation edits, acknowledgments, short "continue"
messages) skip research to keep latency low.

**When to use**

- Quick fact-finding before answering — API docs, release notes, error lookups
- Default research module when latency matters more than depth
- Prefer over `deephop` for ideation passes and routine lookups
- Pair with `tools` so the model can search again during the final completion

**Parameters**

- `max_queries` — maximum search queries extracted per request. Default: `3`
- `max_searches` — maximum web searches per request. Default: `2`
- `max_url_reads` — maximum full-page URL reads per request. Default: `1`
- `max_chars` — maximum research content characters retained. Default: `30000`
- `trigger` — research gate: `heuristic` (default) or `llm` (cheap yes/no classifier)
- `cache_brief` — *(experimental)* reuse the last research brief when the same user
  question appears again within a request session. Default: `false`

```bash
harbor boost modules add quickhop
harbor config set HARBOR_BOOST_QUICKHOP_MAX_QUERIES 3
harbor config set HARBOR_BOOST_QUICKHOP_MAX_SEARCHES 2
harbor config set HARBOR_BOOST_QUICKHOP_MAX_URL_READS 1
harbor config set HARBOR_BOOST_QUICKHOP_MAX_CHARS 30000
harbor config set HARBOR_BOOST_QUICKHOP_TRIGGER heuristic
harbor config set HARBOR_BOOST_QUICKHOP_CACHE_BRIEF false
harbor config set HARBOR_BOOST_TAVILY_API_KEY <key>
# or
harbor config set HARBOR_BOOST_SEARXNG_URL http://searxng:8080
```

**Standalone**

```bash
docker run \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \\
  -e "HARBOR_BOOST_MODULES=quickhop" \\
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

STATUS_PREFIX = "Quickhop research"
BRIEF_CACHE_KEY = "quickhop_brief_cache"


def format_skipped_status(gate_reason: str) -> str:
    """Short status line for emit_status when quickhop passes through."""
    return workflow_mod.format_skipped_status(STATUS_PREFIX, gate_reason)


def format_query_status(query_count: int) -> str:
    """Status line before one-hop research, matching deephop query-count style."""
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
        f"{STATUS_PREFIX}: {query_count} {query_noun}, read {pages_read} {url_noun}..."
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


def research_skip_reason(chat: "ch.Chat") -> str | None:
    """Return a pass-through reason when research should be skipped, else None."""
    skip = orchestrate.research_skip_reason(chat)
    if skip:
        return skip

    return None


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


async def research_gate_reason(chat: "ch.Chat", llm: "llm.LLM") -> tuple[str, int]:
    """Return pass-through reason or ``triggered``, plus cheap-LLM classifier calls."""
    skip = research_skip_reason(chat)
    if skip:
        return skip, 0

    text = orchestrate.last_user_text(chat)
    if getattr(llm, "module", None) == ID_PREFIX:
        return "triggered", 0

    if orchestrate.uses_llm_trigger(boost_config.QUICKHOP_TRIGGER.value):
        if await classify_needs_research(chat, llm, text):
            return "triggered", 1
        return "llm_classifier_no", 1

    if research_heuristic(text):
        return "triggered", 0
    return "heuristic_no_match", 0


def research_heuristic(text: str) -> bool:
    """Return True when heuristic mode should run smash-and-grab research."""
    return deliverable.has_research_signals((text or "").strip())


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
        max_queries=boost_config.QUICKHOP_MAX_QUERIES.value,
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


async def _execute_research(
    chat: "ch.Chat",
    llm: "llm.LLM",
    message: str,
    queries: list[str],
    budget: budget_mod.ResearchBudget,
) -> tuple[brief_mod.ResearchBrief, int]:
    await llm.emit_status(format_query_status(len(queries)))
    brief = await gather_research(queries, budget, llm)
    await llm.emit_status(
        format_gathered_status(
            query_count=len(queries),
            pages_read=len(brief.pages),
        )
    )
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
        cache_brief_enabled=boost_config.QUICKHOP_CACHE_BRIEF.value,
        format_skipped=format_skipped_status,
        research_gate_reason=research_gate_reason,
        plan_queries=extract_search_queries,
        execute_research=_execute_research,
        no_queries_reason="no_queries_extracted",
        no_queries_log="No queries extracted, passing through",
        query_failure_log="query extraction failed",
        query_failure_note_label="Query extraction",
        query_failure_status="query planning failed, continuing without live data...",
        query_failure_metric_key="query_extraction_failed",
    )
