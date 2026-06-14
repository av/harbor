"""Workflow helpers for agentic Boost modules."""


async def complete_or_defer(llm, config: dict | None = None):
  """Stream the final completion unless the workflow defers it to a later step."""
  if config and config.get("defer_final"):
    return None
  return await llm.stream_final_completion()