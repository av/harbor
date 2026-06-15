"""Workflow helpers for agentic Boost modules."""

import research.brief as brief_mod
import research.debug_metrics as debug_metrics


def failure_brief(query: str, note: str) -> brief_mod.ResearchBrief:
  """Build a finalized brief when query planning or research fails."""
  brief = brief_mod.ResearchBrief(query=query)
  brief.add_note(note)
  return brief_mod.finalize_brief(brief)


def anchor_deferred_draft(chat, text: str, config: dict | None = None) -> None:
  """Record a deferred draft in chat for downstream workflow modules.

  When the tail is already an assistant message (for example from a
  ``stream_chat_completion(emit=False)`` draft), replace it so downstream
  modules audit the scoped or revised answer rather than a pre-revision draft.
  """
  if not config or not config.get("defer_final"):
    return
  anchored = (text or "").strip()
  if not anchored:
    return
  if chat.tail.role == "assistant":
    chat.tail.content = anchored
  else:
    chat.assistant(anchored)


async def complete_or_defer(llm, config: dict | None = None):
  """Stream the final completion unless the workflow defers it to a later step."""
  if config and config.get("defer_final"):
    return None

  summary = debug_metrics.final_status_summary(llm)
  if summary:
    await llm.emit_status(summary)

  return await llm.stream_final_completion()