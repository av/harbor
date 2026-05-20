"""Shared utilities for Boost API compatibility layers.

Contains chunk parsing, SSE formatting, and constants used by both
anthropic_compat.py and responses_compat.py.
"""

import json

import dotty

REQUEST_ID_HEADER = "request-id"


def get_chunk_content(chunk):
  return dotty.get(chunk, "choices.0.delta.content", "")


def get_chunk_reasoning(chunk):
  """Extract reasoning/thinking content from a streaming chunk.

  OpenAI-compatible backends may return reasoning content via:
  - choices[0].delta.reasoning_content (OpenAI o1/o3, OpenRouter)
  - choices[0].delta.reasoning (some backends)
  """
  val = dotty.get(chunk, "choices.0.delta.reasoning_content", "")
  if val:
    return val
  return dotty.get(chunk, "choices.0.delta.reasoning", "")


def get_chunk_tool_calls(chunk):
  return dotty.get(chunk, "choices.0.delta.tool_calls", [])


def get_chunk_usage(chunk):
  return dotty.get(chunk, "usage") or {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
  }


def sse_event(event_type, data):
  return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"
