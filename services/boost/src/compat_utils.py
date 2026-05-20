"""Shared utilities for Boost API compatibility layers.

Contains chunk parsing, SSE formatting, ID normalization, and constants
used by both anthropic_compat.py and responses_compat.py.
"""

import json
import re

import dotty

REQUEST_ID_HEADER = "request-id"
OPENAI_REQUEST_ID_HEADER = "x-request-id"
ANTHROPIC_VERSION_HEADER = "anthropic-version"
ANTHROPIC_VERSION = "2023-06-01"

# Tool use / tool call ID prefix patterns
_KNOWN_PREFIXES_RE = re.compile(r"^(toolu_|call_|chatcmpl-)")


def to_anthropic_tool_id(raw_id: str) -> str:
    """Ensure a tool use ID has the ``toolu_`` prefix Anthropic clients expect.

    If *raw_id* already starts with ``toolu_`` it is returned unchanged.
    Otherwise the existing known prefix (``call_``, ``chatcmpl-``, etc.) is
    stripped and ``toolu_`` is prepended.  Bare IDs without a known prefix
    are simply prefixed.
    """
    if not raw_id:
        return raw_id
    if raw_id.startswith("toolu_"):
        return raw_id
    core = _KNOWN_PREFIXES_RE.sub("", raw_id, count=1)
    return f"toolu_{core}"


def to_openai_tool_id(raw_id: str) -> str:
    """Ensure a tool call ID has the ``call_`` prefix OpenAI clients expect.

    If *raw_id* already starts with ``call_`` it is returned unchanged.
    Otherwise the existing known prefix (``toolu_``, ``chatcmpl-``, etc.) is
    stripped and ``call_`` is prepended.  Bare IDs without a known prefix
    are simply prefixed.
    """
    if not raw_id:
        return raw_id
    if raw_id.startswith("call_"):
        return raw_id
    core = _KNOWN_PREFIXES_RE.sub("", raw_id, count=1)
    return f"call_{core}"


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


def get_chunk_refusal(chunk):
  return dotty.get(chunk, "choices.0.delta.refusal", "")


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
