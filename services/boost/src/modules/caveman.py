"""Smash-and-grab pre-answer web research for Harbor Boost."""

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

```bash
harbor boost modules add caveman
harbor config set HARBOR_BOOST_CAVEMAN_MAX_SEARCHES 2
harbor config set HARBOR_BOOST_CAVEMAN_MAX_URL_READS 1
harbor config set HARBOR_BOOST_CAVEMAN_MAX_CHARS 30000
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
RESEARCH_SIGNAL_RE = re.compile(
  r"\b(?:"
  r"latest|current|today|recent(?:ly)?|20\d{2}|version|release|changelog|"
  r"documentat(?:ion|e)|api\s+reference|breaking\s+change|migrate|migration|"
  r"compatibility|deprecat(?:e|ed|ion)|best\s+practice|compare|versus|vs\.?|"
  r"benchmark|pricing|availability|error\s+code|stack\s*overflow|lookup|search\s+for"
  r")\b",
  re.IGNORECASE,
)

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


class SearchQueryPlan(BaseModel):
  queries: list[str] = Field(
    description="Focused web search queries, ordered by usefulness.",
    min_length=1,
    max_length=3,
  )


def _last_user_text(chat: "ch.Chat") -> str:
  node = chat.match_one(role="user", index=-1)
  return (node.content or "").strip() if node else ""


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
  if deliverable.is_coding_deliverable(chat) and not has_research_signals(text):
    return True
  return False


def needs_research(chat: "ch.Chat", llm: "llm.LLM") -> bool:
  """Return True when this turn should run smash-and-grab web research."""
  if should_skip_research(chat):
    return False
  if getattr(llm, "module", None) == ID_PREFIX:
    return True
  return research_heuristic(_last_user_text(chat))


def research_heuristic(text: str) -> bool:
  text = (text or "").strip()
  if not text or len(text) < 8:
    return False
  if has_research_signals(text):
    return True
  return "?" in text and len(text) > 20


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


async def extract_search_queries(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
) -> list[str]:
  intermediate = _cheap_llm(llm)
  result = await intermediate.chat_completion(
    prompt=QUERY_EXTRACTION_PROMPT,
    conversation=chat,
    message=message,
    schema=SearchQueryPlan,
    params={"temperature": 0.2},
    resolve=True,
  )

  queries = result.get("queries", []) if isinstance(result, dict) else []
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
  return cleaned[:3]


def _page_read_char_limit(budget: budget_mod.ResearchBudget) -> int:
  remaining = budget.remaining_chars()
  if budget.max_url_reads <= 0:
    return remaining
  return max(1000, remaining // max(1, budget.max_url_reads))


async def gather_research(
  queries: list[str],
  budget: budget_mod.ResearchBudget,
) -> brief_mod.ResearchBrief:
  brief = brief_mod.ResearchBrief()
  max_results = max(1, config.TOOLS_SEARCH_MAX_RESULTS.value)

  for query in queries:
    if not budget.can_search():
      brief.add_note("Search budget exhausted before all queries ran.")
      break

    try:
      budget.record_search()
      awaitable_status = f"Searching: {query[:80]}"
      logger.info(awaitable_status)
      results_text = await fetch.web_search(query, max_results=max_results)
      results_text = budget.trim_to_remaining(results_text)
      brief.add_search_results(query, results_text)
    except budget_mod.BudgetExceeded as exc:
      logger.warning(f"{ID_PREFIX}: {exc}")
      brief.add_note(str(exc))
      break
    except Exception as exc:
      logger.error(f"{ID_PREFIX}: search failed for '{query}': {exc}")
      brief.add_note(f"Search failed for '{query}': {exc}")

  for source in brief.searches:
    if not source.url or not budget.can_read_url():
      break

    try:
      budget.record_url_read()
      logger.info(f"Reading URL: {source.url}")
      page_text = await fetch.read_url(
        source.url,
        max_chars=_page_read_char_limit(budget),
      )
      page_text = budget.trim_to_remaining(page_text)
      brief.add_page(source.url, page_text, title=source.title)
    except budget_mod.BudgetExceeded as exc:
      logger.warning(f"{ID_PREFIX}: {exc}")
      brief.add_note(str(exc))
      break
    except Exception as exc:
      logger.warning(f"{ID_PREFIX}: read_url failed for {source.url}: {exc}")
      brief.add_note(f"Could not read {source.url}: {exc}")

  return brief


async def apply(chat: "ch.Chat", llm: "llm.LLM", config: dict | None = None):
  message = _last_user_text(chat)
  if not message:
    logger.warning(f"{ID_PREFIX}: No user message found, passing through")
    return await workflow_mod.complete_or_defer(llm, config)

  if not needs_research(chat, llm):
    logger.debug(f"{ID_PREFIX}: Skipping research for: {message[:80]}...")
    return await workflow_mod.complete_or_defer(llm, config)

  await llm.emit_status("Caveman research: planning queries...")
  budget = budget_mod.budget_from_config(ID_PREFIX)

  try:
    queries = await extract_search_queries(chat, llm, message)
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: query extraction failed: {exc}")
    brief = brief_mod.ResearchBrief(query=message)
    brief.add_note(f"Query extraction failed: {exc}")
    chat.system(brief_mod.render_to_system(brief))
    return await workflow_mod.complete_or_defer(llm, config)

  if not queries:
    logger.warning(f"{ID_PREFIX}: No queries extracted, passing through")
    return await workflow_mod.complete_or_defer(llm, config)

  await llm.emit_status(f"Caveman research: {len(queries)} quer{'y' if len(queries) == 1 else 'ies'}...")
  brief = await gather_research(queries, budget)
  if not brief.query:
    brief.query = message

  chat.system(brief_mod.render_to_system(brief))
  await workflow_mod.complete_or_defer(llm, config)