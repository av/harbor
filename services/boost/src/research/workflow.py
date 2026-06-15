"""Workflow helpers for agentic Boost modules."""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import research.brief as brief_mod
import research.brief_cache as brief_cache
import research.budget as budget_mod
import research.debug_metrics as debug_metrics
import research.orchestrate as orchestrate

if TYPE_CHECKING:
  import chat as ch
  import llm


def failure_brief(query: str, note: str) -> brief_mod.ResearchBrief:
  """Build a finalized brief when query planning or research fails."""
  brief = brief_mod.ResearchBrief(query=query)
  brief.add_note(note)
  return brief_mod.finalize_brief(brief)


def anchor_deferred_draft(chat, text: str, config: dict | None = None) -> None:
  """Record a deferred draft in chat for downstream workflow modules.

  When the current workflow step already left an assistant draft after the
  latest user turn (for example from ``stream_chat_completion(emit=False)``),
  replace that draft so downstream modules audit the scoped or revised answer.
  Assistant messages from earlier user turns are preserved; only in-turn drafts
  between the latest user message and ``chat.tail`` are replaced.
  """
  if not config or not config.get("defer_final"):
    return
  anchored = (text or "").strip()
  if not anchored:
    return

  latest_user = None
  node = chat.tail
  while node is not None:
    if node.role == "user":
      latest_user = node
      break
    node = node.parent

  if latest_user is None:
    chat.assistant(anchored)
    return

  node = chat.tail
  while node is not None and node is not latest_user:
    if node.role == "assistant":
      node.content = anchored
      return
    node = node.parent

  chat.assistant(anchored)


def format_skipped_status(module_label: str, gate_reason: str) -> str:
  """Short status line for emit_status when a module passes through."""
  reason = (gate_reason or "unknown").strip()
  return f"{module_label}: skipped ({reason})"


async def emit_final(llm: "llm.LLM", final_text: str) -> None:
  """Emit the user-visible final answer when a module owns delivery."""
  if final_text:
    await llm.emit_message(final_text)


async def anchor_and_emit_final(
  llm: "llm.LLM",
  chat,
  text: str,
  config: dict | None = None,
) -> str:
  """Anchor a deferred draft and emit it unless the workflow defers final delivery."""
  anchored = (text or "").strip()
  anchor_deferred_draft(chat, anchored, config)
  if config and config.get("defer_final"):
    return anchored

  await emit_final(llm, anchored)
  return anchored


async def complete_or_defer(llm, config: dict | None = None):
  """Stream the final completion unless the workflow defers it to a later step."""
  if config and config.get("defer_final"):
    return None

  summary = debug_metrics.final_status_summary(llm)
  if summary:
    await llm.emit_status(summary)

  return await llm.stream_final_completion()


async def apply_research_module(
  chat: "ch.Chat",
  llm: "llm.LLM",
  config: dict | None,
  *,
  module_id: str,
  logger,
  status_prefix: str,
  brief_cache_key: str,
  cache_brief_enabled: bool,
  format_skipped: Callable[[str], str],
  research_gate_reason: Callable[
    ["ch.Chat", "llm.LLM"],
    Awaitable[tuple[str, int]],
  ],
  plan_queries: Callable[
    ["ch.Chat", "llm.LLM", str],
    Awaitable[list[str]],
  ],
  execute_research: Callable[
    ["ch.Chat", "llm.LLM", str, list[str], budget_mod.ResearchBudget],
    Awaitable[tuple[brief_mod.ResearchBrief, int]],
  ],
  no_queries_reason: str,
  no_queries_log: str,
  query_failure_log: str,
  query_failure_note_label: str,
  query_failure_status: str,
  query_failure_metric_key: str,
) -> None:
  """Shared apply() scaffold for caveman/ponytail-style pre-answer web research."""
  timer = debug_metrics.DebugTimer()
  extra_calls = 0
  message = orchestrate.last_user_text(chat)
  if not message:
    logger.warning(f"{module_id}: No user message found, passing through")
    await llm.emit_status(format_skipped("empty_message"))
    debug_metrics.record_module(
      module_id,
      debug_metrics.skipped_payload("empty_message", duration_ms=timer.elapsed_ms()),
      logger=logger,
    )
    return await complete_or_defer(llm, config)

  gate_reason, classifier_calls = await research_gate_reason(chat, llm)
  extra_calls += classifier_calls
  if gate_reason != "triggered":
    await llm.emit_status(format_skipped(gate_reason))
    debug_metrics.record_module(
      module_id,
      debug_metrics.skipped_payload(
        gate_reason,
        duration_ms=timer.elapsed_ms(),
        extra_calls=extra_calls,
      ),
      logger=logger,
      gate_reason=gate_reason,
    )
    return await complete_or_defer(llm, config)

  cached_brief = brief_cache.get_cached_brief(
    brief_cache_key,
    message,
    enabled=cache_brief_enabled,
  )
  if cached_brief is not None:
    logger.debug(f"{module_id}: Reusing cached brief for same question")
    await llm.emit_status(f"{status_prefix}: using cached brief...")
    if not cached_brief.query:
      cached_brief.query = message
    chat.system(brief_mod.render_to_system(cached_brief))
    debug_metrics.record_module(
      module_id,
      debug_metrics.triggered_payload(
        "triggered",
        duration_ms=timer.elapsed_ms(),
        extra_calls=extra_calls,
        cached_brief=True,
      ),
      logger=logger,
    )
    return await complete_or_defer(llm, config)

  await llm.emit_status(f"{status_prefix}: planning queries...")
  budget = budget_mod.budget_from_config(module_id)

  try:
    queries = await plan_queries(chat, llm, message)
    extra_calls += 1
  except Exception as exc:
    logger.error(f"{module_id}: {query_failure_log}: {exc}")
    brief = failure_brief(message, f"{query_failure_note_label} failed: {exc}")
    await llm.emit_status(f"{status_prefix}: {query_failure_status}")
    chat.system(brief_mod.render_to_system(brief))
    debug_metrics.record_module(
      module_id,
      debug_metrics.triggered_payload(
        "triggered",
        duration_ms=timer.elapsed_ms(),
        extra_calls=extra_calls,
        **{query_failure_metric_key: True},
      ),
      logger=logger,
    )
    return await complete_or_defer(llm, config)

  if not queries:
    logger.warning(f"{module_id}: {no_queries_log}")
    await llm.emit_status(format_skipped(no_queries_reason))
    debug_metrics.record_module(
      module_id,
      debug_metrics.skipped_payload(
        no_queries_reason,
        duration_ms=timer.elapsed_ms(),
        extra_calls=extra_calls,
      ),
      logger=logger,
      gate_reason=no_queries_reason,
    )
    return await complete_or_defer(llm, config)

  brief, research_extra_calls = await execute_research(chat, llm, message, queries, budget)
  extra_calls += research_extra_calls

  if not brief.query:
    brief.query = message

  if not brief_mod.has_usable_research(brief):
    await llm.emit_status(
      f"{status_prefix}: research unavailable, continuing without live data..."
    )

  brief_cache.store_cached_brief(
    brief_cache_key,
    message,
    brief,
    enabled=cache_brief_enabled,
  )
  chat.system(brief_mod.render_to_system(brief))
  debug_metrics.record_module(
    module_id,
    debug_metrics.triggered_payload(
      "triggered",
      duration_ms=timer.elapsed_ms(),
      extra_calls=extra_calls,
      queries=len(queries),
      searches=len(brief.searches),
      pages=len(brief.pages),
    ),
    logger=logger,
  )
  await complete_or_defer(llm, config)