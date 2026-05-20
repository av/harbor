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


def extract_annotations(message: dict, text: str = "") -> list:
  """Extract annotations from a Chat Completions message and convert to
  Responses API ``url_citation`` format.

  Sources checked (in order):

  1. ``message.annotations`` — the OpenAI Chat Completions annotation
     format (used by OpenAI web-search responses and OpenRouter).  Each
     entry wraps a ``url_citation`` with ``start_index``/``end_index``,
     ``title``, and ``url``.

  2. ``message.citations`` / top-level ``citations`` — the Perplexity
     format.  A flat list of URL strings with no positional or title
     metadata.  Since there are no character indices, we synthesize
     ``start_index = end_index = 0`` and ``title = ""`` so the SDK
     can still parse the objects.

  Returns a list of Responses API annotation dicts (``type: url_citation``).
  """
  annotations = []

  # Source 1: OpenAI message.annotations (structured citations)
  raw_annotations = message.get("annotations") or []
  for ann in raw_annotations:
    if not isinstance(ann, dict):
      continue
    ann_type = ann.get("type")
    if ann_type == "url_citation":
      citation = ann.get("url_citation", {})
      annotations.append({
        "type": "url_citation",
        "start_index": citation.get("start_index", 0),
        "end_index": citation.get("end_index", 0),
        "url": citation.get("url", ""),
        "title": citation.get("title", ""),
      })
    elif ann_type == "file_citation":
      annotations.append({
        "type": "file_citation",
        "file_id": ann.get("file_id", ""),
        "filename": ann.get("filename", ""),
        "index": ann.get("index", 0),
      })
    elif ann_type == "file_path":
      annotations.append({
        "type": "file_path",
        "file_id": ann.get("file_id", ""),
        "index": ann.get("index", 0),
      })

  # Source 2: Perplexity-style citations (flat URL list)
  if not annotations:
    raw_citations = message.get("citations") or []
    for url in raw_citations:
      if isinstance(url, str) and url:
        annotations.append({
          "type": "url_citation",
          "start_index": 0,
          "end_index": 0,
          "url": url,
          "title": "",
        })

  return annotations


def sse_event(event_type, data):
  return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


def extract_boost_params(body: dict) -> dict:
  """Extract ``@boost_``-prefixed params from a request's ``metadata`` dict.

  Both Anthropic and Responses API requests carry an optional ``metadata``
  dict.  Any key inside it that starts with ``@boost_`` is forwarded into
  the OpenAI body so it reaches ``LLM.split_params()`` and becomes available
  as a boost param (e.g. ``@boost_workflow``, ``@boost_pad_size``).
  """
  metadata = body.get("metadata")
  if not metadata or not isinstance(metadata, dict):
    return {}

  return {k: v for k, v in metadata.items() if k.startswith("@boost_")}


async def parse_sse_chunks(response_stream):
  """Yield parsed JSON dicts from an OpenAI-format SSE stream.

  Harbor's ``LLM.serve()`` yields stringified SSE chunks in the form
  ``data: {...}\\n\\n`` or ``data: [DONE]``.  This async generator handles
  decoding, line splitting, and JSON parsing — the boilerplate both
  streaming converters previously duplicated.

  The inner *response_stream* is explicitly closed in a ``finally`` block
  so that client disconnects (which raise ``GeneratorExit`` on the caller)
  propagate cleanup to the underlying ``LLM.generator()`` and stop the
  background task from writing to a dead queue.
  """
  try:
    async for raw_chunk in response_stream:
      chunk_str = raw_chunk if isinstance(raw_chunk, str) else raw_chunk.decode("utf-8")

      for line in chunk_str.strip().split("\n"):
        line = line.strip()
        if not line or line == "data: [DONE]" or not line.startswith("data: "):
          continue

        try:
          yield json.loads(line[6:])
        except (json.JSONDecodeError, TypeError):
          continue
  finally:
    # Ensure the upstream async generator is closed even when the
    # consumer is interrupted (client disconnect / GeneratorExit).
    if hasattr(response_stream, "aclose"):
      await response_stream.aclose()
