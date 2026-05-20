from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, StreamingResponse

import json
import time

import dotty
import format
import shortuuid
import log
import mapper
import llm as llm_mod
from llm import BackendError
from auth import get_api_key
from compat_utils import (
    OPENAI_REQUEST_ID_HEADER,
    RATE_LIMIT_FORWARD_HEADERS,
    SSE_HEADERS,
    SSE_KEEPALIVE_INTERVAL,
    _get_finish_reason,
    extract_annotations as _extract_annotations,
    extract_boost_params as _extract_boost_params,
    get_chunk_annotations as _get_chunk_annotations,
    get_chunk_content as _get_chunk_content,
    get_chunk_reasoning as _get_chunk_reasoning,
    get_chunk_refusal as _get_chunk_refusal,
    get_chunk_tool_calls as _get_chunk_tool_calls,
    get_chunk_usage as _get_chunk_usage,
    parse_sse_chunks as _parse_sse_chunks,
    sse_event as _sse_event,
    sse_event_with_retry as _sse_event_with_retry,
    sse_keepalive_comment as _sse_keepalive,
    to_openai_tool_id as _to_openai_tool_id,
)

logger = log.setup_logger(__name__)
responses_compatible_routes = APIRouter()


ERROR_TYPE_MAP = {
  400: "invalid_request_error",
  401: "authentication_error",
  403: "permission_error",
  404: "not_found_error",
  409: "conflict_error",
  422: "invalid_request_error",
  429: "rate_limit_error",
  500: "server_error",
}


def _responses_error(status_code, message, error_type=None, error_code=None, request_id=None):
  if error_type is None:
    error_type = ERROR_TYPE_MAP.get(status_code, "server_error")
  body = {
    "error": {
      "message": message,
      "type": error_type,
      "param": None,
      "code": error_code,
    }
  }
  headers = {}
  if request_id:
    headers[OPENAI_REQUEST_ID_HEADER] = request_id
  return JSONResponse(status_code=status_code, content=body, headers=headers)


def _make_usage(input_tokens=0, output_tokens=0, total_tokens=None, reasoning_tokens=0):
  """Build a usage dict with the token detail sub-objects the SDK requires."""
  if total_tokens is None:
    total_tokens = input_tokens + output_tokens
  return {
    "input_tokens": input_tokens,
    "output_tokens": output_tokens,
    "total_tokens": total_tokens,
    "input_tokens_details": {"cached_tokens": 0},
    "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
  }


# --- Request conversion (Responses -> Chat Completions) ---


def _convert_input_to_messages(body: dict):
  """Convert Responses API input + instructions to Chat Completions messages."""
  messages = []

  instructions = body.get("instructions")
  if instructions:
    messages.append({"role": "system", "content": instructions})

  inp = body.get("input")
  if inp is None:
    return messages

  # Simple string input -> single user message
  if isinstance(inp, str):
    messages.append({"role": "user", "content": inp})
    return messages

  if not isinstance(inp, list):
    messages.append({"role": "user", "content": str(inp)})
    return messages

  # Array of input items
  for item in inp:
    if isinstance(item, str):
      messages.append({"role": "user", "content": item})
      continue

    if not isinstance(item, dict):
      messages.append({"role": "user", "content": str(item)})
      continue

    item_type = item.get("type")

    if item_type == "message":
      role = item.get("role", "user")
      content = item.get("content", "")

      if isinstance(content, str):
        messages.append({"role": role, "content": content})
      elif isinstance(content, list):
        messages.append({"role": role, "content": _convert_content_parts(content)})
      else:
        messages.append({"role": role, "content": str(content)})

    elif item_type == "function_call":
      # Previous response output items echoed back for multi-turn context.
      # Convert to an assistant message with tool_calls so the backend
      # sees the tool invocation the tool result corresponds to.
      # Consecutive function_call items are merged into a single assistant
      # message (the backend returned them together in one turn).
      raw_id = item.get("call_id") or item.get("id") or ""
      tc_entry = {
        "id": _to_openai_tool_id(raw_id) if raw_id else "",
        "type": "function",
        "function": {
          "name": item.get("name", ""),
          "arguments": item.get("arguments", "{}"),
        },
      }

      # Merge into the previous assistant message if it exists and has tool_calls
      if (
        messages
        and messages[-1].get("role") == "assistant"
        and "tool_calls" in messages[-1]
      ):
        messages[-1]["tool_calls"].append(tc_entry)
      else:
        messages.append({
          "role": "assistant",
          "content": None,
          "tool_calls": [tc_entry],
        })

    elif item_type == "function_call_output":
      raw_call_id = item.get("call_id", "")
      messages.append({
        "role": "tool",
        "tool_call_id": _to_openai_tool_id(raw_call_id) if raw_call_id else "",
        "content": item.get("output", ""),
      })

    elif item_type == "item_reference":
      # References to previous response items; skip in translation
      pass

    elif item_type in ("reasoning", "computer_call_output"):
      # reasoning: thinking from a previous response; no backend equivalent
      # computer_call_output: OpenAI computer use; not supported
      logger.debug("Skipping %s input item (not mapped to Chat Completions)", item_type)

    else:
      # Unknown item type; skip with a warning so callers can debug
      if item_type:
        logger.warning("Unknown input item type '%s' skipped", item_type)

  return messages


def _convert_content_parts(content_parts):
  """Convert Responses API content parts to Chat Completions content format."""
  openai_parts = []

  for part in content_parts:
    if not isinstance(part, dict):
      openai_parts.append({"type": "text", "text": str(part)})
      continue

    part_type = part.get("type")

    if part_type == "input_text":
      openai_parts.append({"type": "text", "text": part.get("text", "")})

    elif part_type == "input_image":
      image_url = part.get("image_url")
      detail = part.get("detail")
      if image_url:
        img_part = {"url": image_url}
        if detail:
          img_part["detail"] = detail
        openai_parts.append({
          "type": "image_url",
          "image_url": img_part,
        })
      else:
        # file_id reference — best-effort passthrough
        file_id = part.get("file_id", "")
        if file_id:
          img_part = {"url": file_id}
          if detail:
            img_part["detail"] = detail
          openai_parts.append({
            "type": "image_url",
            "image_url": img_part,
          })

    elif part_type == "input_audio":
      data = part.get("data", "")
      fmt = part.get("format", "wav")
      openai_parts.append({
        "type": "input_audio",
        "input_audio": {"data": data, "format": fmt},
      })

    elif part_type == "input_file":
      # File uploads have no direct Chat Completions equivalent.
      # Best-effort: if the file contains text, pass it through as text.
      file_text = part.get("filename") or part.get("file_id") or ""
      logger.warning(
        "input_file content part has no Chat Completions equivalent and "
        "will be represented as a text placeholder (file: %s)",
        file_text,
      )
      openai_parts.append({
        "type": "text",
        "text": f"[Attached file: {file_text}]" if file_text else "[Attached file]",
      })

    elif part_type == "text":
      openai_parts.append({"type": "text", "text": part.get("text", "")})

    else:
      # Unknown part type, pass text if available
      text = part.get("text") or part.get("content") or str(part)
      openai_parts.append({"type": "text", "text": text})

  # If all parts are plain text, collapse to a single string
  if all(p.get("type") == "text" for p in openai_parts):
    text = "\n".join(p["text"] for p in openai_parts)
    return text

  return openai_parts


_WEB_SEARCH_TOOL_DEF = {
  "type": "function",
  "function": {
    "name": "web_search",
    "description": (
      "Search the live web and return a short ranked result set. "
      "Use absolute dates for time-sensitive searches."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "Search query.",
        },
      },
      "required": ["query"],
    },
  },
}

# Built-in tool types that have no Harbor equivalent
_UNSUPPORTED_BUILTIN_TOOLS = {
  "file_search", "code_interpreter",
  "computer_use_preview", "computer",
  "image_generation",
  "local_shell", "function_shell",
  "apply_patch",
  "mcp",
  "custom",
  "namespace",
  "tool_search",
}

# Built-in tool types that map to Harbor's web_search
_WEB_SEARCH_TYPES = {"web_search_preview", "web_search"}


def _convert_tools(body: dict):
  """Convert Responses API tools to Chat Completions tools format.

  Function tools pass through directly. OpenAI built-in ``web_search``
  and ``web_search_preview`` tools are mapped to Harbor Boost's own
  ``web_search`` function tool (from the tools module).
  ``file_search`` and ``code_interpreter`` have no Harbor equivalent
  and are logged as warnings.
  """
  tools = body.get("tools")
  if not tools:
    return []

  openai_tools = []
  has_web_search = False
  for tool in tools:
    tool_type = tool.get("type")
    if tool_type == "function":
      openai_tools.append({
        "type": "function",
        "function": {
          "name": tool.get("name", ""),
          "description": tool.get("description", ""),
          "parameters": tool.get("parameters", {}),
        },
      })
    elif tool_type in _WEB_SEARCH_TYPES:
      if not has_web_search:
        openai_tools.append(_WEB_SEARCH_TOOL_DEF)
        has_web_search = True
    elif tool_type in _UNSUPPORTED_BUILTIN_TOOLS:
      logger.warning(
        "Responses API built-in tool '%s' has no Harbor equivalent and will be skipped",
        tool_type,
      )
  return openai_tools


def _convert_tool_choice(body: dict):
  """Convert Responses API tool_choice to Chat Completions tool_choice.

  Handles string values (``auto``, ``none``, ``required``) and dict
  values. Dict ``type: function`` maps to Chat Completions forced
  function. Dict ``type: web_search_preview`` or ``type: web_search``
  maps to forcing Harbor's ``web_search`` function tool.
  Unsupported built-in types (``file_search``, ``code_interpreter``)
  fall back to ``auto``.
  """
  tc = body.get("tool_choice")
  if tc is None:
    return None
  if isinstance(tc, str):
    # "auto", "none", "required" pass through directly
    return tc
  if isinstance(tc, dict):
    tc_type = tc.get("type")
    if tc_type == "function":
      return {"type": "function", "function": {"name": tc.get("name", "")}}
    if tc_type in _WEB_SEARCH_TYPES:
      return {"type": "function", "function": {"name": "web_search"}}
    if tc_type in _UNSUPPORTED_BUILTIN_TOOLS:
      logger.warning(
        "tool_choice type '%s' has no Harbor equivalent; falling back to 'auto'",
        tc_type,
      )
      return "auto"
  return None


def _build_openai_body(body: dict):
  """Build a Chat Completions request body from a Responses API request."""
  openai_body = {
    "model": body["model"],
    "messages": _convert_input_to_messages(body),
  }

  # Parameter passthrough
  for key in ("temperature", "top_p"):
    if key in body:
      openai_body[key] = body[key]

  if "max_output_tokens" in body:
    openai_body["max_tokens"] = body["max_output_tokens"]

  # user passthrough (used for abuse detection / prompt caching)
  if body.get("user"):
    openai_body["user"] = body["user"]

  # Reasoning/thinking support: map reasoning config to Chat Completions params
  reasoning = body.get("reasoning")
  if reasoning and isinstance(reasoning, dict):
    effort = reasoning.get("effort")
    if effort:
      openai_body["reasoning_effort"] = effort
    # reasoning.summary (or deprecated generate_summary) controls whether
    # the backend produces reasoning summaries.  Pass through so backends
    # that understand this parameter can act on it.
    summary = reasoning.get("summary") or reasoning.get("generate_summary")
    if summary:
      openai_body["reasoning_summary"] = summary

  # text.format -> response_format conversion (structured outputs)
  text_config = body.get("text")
  if text_config and isinstance(text_config, dict):
    fmt = text_config.get("format")
    if fmt and isinstance(fmt, dict):
      fmt_type = fmt.get("type")
      if fmt_type == "json_schema":
        rf = {"type": "json_schema", "json_schema": {}}
        if fmt.get("name"):
          rf["json_schema"]["name"] = fmt["name"]
        if fmt.get("description"):
          rf["json_schema"]["description"] = fmt["description"]
        if fmt.get("schema"):
          rf["json_schema"]["schema"] = fmt["schema"]
        if fmt.get("strict") is not None:
          rf["json_schema"]["strict"] = fmt["strict"]
        openai_body["response_format"] = rf
      elif fmt_type == "json_object":
        openai_body["response_format"] = {"type": "json_object"}

  # Truncation: accept without error. Backends handle their own context windows,
  # so we cannot guarantee truncation behavior — log a warning when requested.
  truncation = body.get("truncation")
  if truncation == "auto":
    logger.warning(
      "truncation 'auto' requested but Harbor Boost cannot guarantee "
      "truncation — backends manage their own context windows"
    )

  # previous_response_id: Harbor Boost does not persist responses
  if body.get("previous_response_id"):
    logger.debug(
      "previous_response_id requested but Harbor Boost does not persist "
      "responses; the referenced response will not be loaded"
    )

  # include: accept without error (used for logprobs, file search results, etc.)
  # Harbor Boost does not support include-based enrichment, but accepting the
  # parameter prevents SDK clients from getting 400 errors.
  if body.get("include"):
    logger.debug("include parameter accepted but not acted on: %s", body["include"])

  # service_tier: accept for SDK compatibility
  if body.get("service_tier"):
    logger.debug("service_tier '%s' accepted but not acted on", body["service_tier"])

  if body.get("stream", False):
    openai_body["stream"] = True
    openai_body["stream_options"] = {"include_usage": True}

  tools = _convert_tools(body)
  if tools:
    openai_body["tools"] = tools

  tool_choice = _convert_tool_choice(body)
  if tool_choice is not None:
    openai_body["tool_choice"] = tool_choice

  # parallel_tool_calls: direct passthrough (OpenAI Chat Completions param)
  if "parallel_tool_calls" in body:
    openai_body["parallel_tool_calls"] = body["parallel_tool_calls"]

  # Forward @boost_ params from metadata into the body for LLM.split_params()
  openai_body.update(_extract_boost_params(body))

  return openai_body


# --- Response conversion (Chat Completions -> Responses) ---


def _build_output_items(openai_result):
  """Convert Chat Completions result to Responses API output items.

  The SDK computes ``Response.output_text`` client-side by concatenating
  all ``output_text`` blocks from ``message`` output items, so the server
  does not need to send a separate ``output_text`` field.
  """
  output = []

  # Reasoning/thinking content — emitted as a reasoning output item before the message
  message = dotty.get(openai_result, "choices.0.message", {})
  reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
  if reasoning:
    output.append({
      "type": "reasoning",
      "id": f"rs_{shortuuid.random()}",
      "status": "completed",
      "summary": [
        {
          "type": "summary_text",
          "text": str(reasoning),
        }
      ],
    })

  content = dotty.get(openai_result, "choices.0.message.content")
  refusal = dotty.get(openai_result, "choices.0.message.refusal")
  tool_calls = dotty.get(openai_result, "choices.0.message.tool_calls", [])

  # Extract annotations from the Chat Completions message (OpenAI web-search
  # url_citations, Perplexity citations, etc.)
  annotations = _extract_annotations(message)

  if refusal:
    output.append({
      "type": "message",
      "id": f"msg_{shortuuid.random()}",
      "status": "completed",
      "role": "assistant",
      "content": [
        {
          "type": "refusal",
          "refusal": str(refusal),
        }
      ],
    })
  elif content:
    output.append({
      "type": "message",
      "id": f"msg_{shortuuid.random()}",
      "status": "completed",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": format.clean_text_preserve_newlines(str(content)),
          "annotations": annotations,
        }
      ],
    })

  for tc in tool_calls:
    func = tc.get("function", {})
    raw_id = tc.get("id") or f"call_{shortuuid.random()}"
    tc_id = _to_openai_tool_id(raw_id)
    output.append({
      "type": "function_call",
      "id": tc_id,
      "call_id": tc_id,
      "name": func.get("name", ""),
      "arguments": func.get("arguments", "{}"),
      "status": "completed",
    })

  # Always have at least one output item
  if not output:
    output.append({
      "type": "message",
      "id": f"msg_{shortuuid.random()}",
      "status": "completed",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "",
          "annotations": [],
        }
      ],
    })

  return output


def _map_status(finish_reason):
  """Map Chat Completions finish_reason to Responses API status."""
  if finish_reason == "length":
    return "incomplete"
  if finish_reason == "content_filter":
    return "incomplete"
  return "completed"


def _incomplete_reason(finish_reason):
  """Return the incomplete_details reason for a given finish_reason, or None."""
  if finish_reason == "length":
    return "max_output_tokens"
  if finish_reason == "content_filter":
    return "content_filter"
  return None


def _build_responses_response(openai_result, request_model, response_id, request_body=None):
  """Build a full Responses API response object."""
  finish_reason = dotty.get(openai_result, "choices.0.finish_reason", "stop")
  usage = dotty.get(openai_result, "usage", {})
  output = _build_output_items(openai_result)
  status = _map_status(finish_reason)

  # Extract reasoning tokens from completion_tokens_details if available
  reasoning_tokens = dotty.get(
    openai_result, "usage.completion_tokens_details.reasoning_tokens", 0
  ) or 0

  # Passthrough metadata from request if provided
  metadata = {}
  if request_body and isinstance(request_body.get("metadata"), dict):
    metadata = request_body["metadata"]

  # Determine truncation value from request (SDK sends as string, not dict)
  truncation = "disabled"
  if request_body:
    trunc = request_body.get("truncation")
    if trunc == "auto":
      truncation = "auto"

  # Reflect the parallel_tool_calls value from the request (default: True)
  parallel_tool_calls = True
  if request_body and "parallel_tool_calls" in request_body:
    parallel_tool_calls = bool(request_body["parallel_tool_calls"])

  # Echo back instructions from request
  instructions = None
  if request_body:
    instructions = request_body.get("instructions")

  # Echo back user from request
  user = None
  if request_body:
    user = request_body.get("user")

  # Echo back reasoning config from request
  reasoning_config = None
  if request_body and request_body.get("reasoning"):
    reasoning_config = request_body["reasoning"]

  now = int(time.time())
  response = {
    "id": response_id,
    "object": "response",
    "created_at": now,
    "status": status,
    "model": request_model,
    "output": output,
    "instructions": instructions,
    "usage": _make_usage(
      input_tokens=usage.get("prompt_tokens", 0),
      output_tokens=usage.get("completion_tokens", 0),
      total_tokens=usage.get("total_tokens", 0),
      reasoning_tokens=reasoning_tokens,
    ),
    "store": False,
    "metadata": metadata,
    "temperature": None,
    "top_p": None,
    "max_output_tokens": None,
    "truncation": truncation,
    "tool_choice": "auto",
    "tools": [],
    "text": {
      "format": {"type": "text"},
    },
    "parallel_tool_calls": parallel_tool_calls,
    "error": None,
    "incomplete_details": {"reason": _incomplete_reason(finish_reason)} if status == "incomplete" else None,
  }

  # completed_at is set only when status is completed
  if status == "completed":
    response["completed_at"] = now

  if user is not None:
    response["user"] = user
  if reasoning_config is not None:
    response["reasoning"] = reasoning_config

  return response


# --- Streaming conversion ---


async def _responses_stream_converter(
  response_stream, request_model, response_id, request_body=None
):
  """Convert Harbor Boost's OpenAI-format SSE stream to Responses API SSE events.

  Emits events in the OpenAI Responses API streaming format:
  - response.created
  - response.output_item.added
  - response.content_part.added
  - response.output_text.delta / response.function_call_arguments.delta
  - response.output_text.done / response.function_call_arguments.done
  - response.content_part.done
  - response.output_item.done
  - response.completed
  """
  created_at = int(time.time())
  seq = 0
  output_index = -1
  reasoning_item_open = False
  reasoning_parts = []
  reasoning_id = None
  text_item_open = False
  text_parts = []
  text_annotations = []
  msg_id = None
  tool_blocks = {}
  input_tokens = 0
  output_tokens = 0
  finish_reason = None

  # Passthrough metadata from request if provided
  metadata = {}
  if request_body and isinstance(request_body.get("metadata"), dict):
    metadata = request_body["metadata"]

  # Determine truncation value from request (SDK sends as string, not dict)
  truncation = "disabled"
  if request_body and request_body.get("truncation") == "auto":
    truncation = "auto"

  # Reflect the parallel_tool_calls value from the request (default: True)
  parallel_tool_calls = True
  if request_body and "parallel_tool_calls" in request_body:
    parallel_tool_calls = bool(request_body["parallel_tool_calls"])

  # Echo back instructions from request
  instructions = None
  if request_body:
    instructions = request_body.get("instructions")

  # Echo back user from request
  user = None
  if request_body:
    user = request_body.get("user")

  # Echo back reasoning config from request
  reasoning_config = None
  if request_body and request_body.get("reasoning"):
    reasoning_config = request_body["reasoning"]

  # Refusal tracking
  refusal_open = False
  refusal_parts = []

  last_event_time = time.monotonic()

  # Skeleton response for the created event
  skeleton = {
    "id": response_id,
    "object": "response",
    "created_at": created_at,
    "status": "in_progress",
    "model": request_model,
    "output": [],
    "instructions": instructions,
    "usage": _make_usage(),
    "store": False,
    "metadata": metadata,
    "temperature": None,
    "top_p": None,
    "max_output_tokens": None,
    "truncation": truncation,
    "tool_choice": "auto",
    "tools": [],
    "text": {"format": {"type": "text"}},
    "parallel_tool_calls": parallel_tool_calls,
    "error": None,
    "incomplete_details": None,
  }

  if user is not None:
    skeleton["user"] = user
  if reasoning_config is not None:
    skeleton["reasoning"] = reasoning_config

  # Include the SSE retry interval in the first event block so the
  # client knows how long to wait before reconnecting after an
  # unexpected disconnect.  Using sse_event_with_retry avoids emitting
  # a standalone retry field that some SDKs (e.g. OpenAI Python)
  # cannot parse (they produce a data-less ServerSentEvent and crash
  # on json()).
  yield _sse_event_with_retry("response.created", {
    "type": "response.created",
    "sequence_number": seq,
    "response": skeleton,
  })
  seq += 1

  yield _sse_event("response.in_progress", {
    "type": "response.in_progress",
    "sequence_number": seq,
    "response": skeleton,
  })
  seq += 1

  stream_error = None

  def _close_reasoning_item():
    """Yield events to close an open reasoning output item. Returns list of SSE strings."""
    nonlocal seq
    events = []
    full_reasoning = "".join(reasoning_parts)

    # reasoning_summary_text.done
    events.append(_sse_event("response.reasoning_summary_text.done", {
      "type": "response.reasoning_summary_text.done",
      "item_id": reasoning_id,
      "output_index": output_index,
      "summary_index": 0,
      "text": full_reasoning,
      "sequence_number": seq,
    }))
    seq += 1

    # reasoning_summary_part.done
    events.append(_sse_event("response.reasoning_summary_part.done", {
      "type": "response.reasoning_summary_part.done",
      "item_id": reasoning_id,
      "output_index": output_index,
      "summary_index": 0,
      "part": {
        "type": "summary_text",
        "text": full_reasoning,
      },
      "sequence_number": seq,
    }))
    seq += 1

    # output_item.done
    events.append(_sse_event("response.output_item.done", {
      "type": "response.output_item.done",
      "output_index": output_index,
      "item": {
        "type": "reasoning",
        "id": reasoning_id,
        "status": "completed",
        "summary": [{
          "type": "summary_text",
          "text": full_reasoning,
        }],
      },
      "sequence_number": seq,
    }))
    seq += 1

    return events

  def _close_text_item():
    """Yield events to close an open text message item. Returns list of SSE strings."""
    nonlocal seq
    events = []
    full_text = "".join(text_parts)

    # Emit annotation.added events for any accumulated annotations
    for ann_idx, ann in enumerate(text_annotations):
      events.append(_sse_event("response.output_text.annotation.added", {
        "type": "response.output_text.annotation.added",
        "item_id": msg_id,
        "output_index": output_index,
        "content_index": 0,
        "annotation_index": ann_idx,
        "annotation": ann,
        "sequence_number": seq,
      }))
      seq += 1

    # output_text.done
    events.append(_sse_event("response.output_text.done", {
      "type": "response.output_text.done",
      "item_id": msg_id,
      "output_index": output_index,
      "content_index": 0,
      "text": full_text,
      "logprobs": [],
      "sequence_number": seq,
    }))
    seq += 1

    # content_part.done
    events.append(_sse_event("response.content_part.done", {
      "type": "response.content_part.done",
      "item_id": msg_id,
      "output_index": output_index,
      "content_index": 0,
      "part": {
        "type": "output_text",
        "text": full_text,
        "annotations": text_annotations,
      },
      "sequence_number": seq,
    }))
    seq += 1

    # output_item.done
    events.append(_sse_event("response.output_item.done", {
      "type": "response.output_item.done",
      "output_index": output_index,
      "item": {
        "type": "message",
        "id": msg_id,
        "status": "completed",
        "role": "assistant",
        "content": [{
          "type": "output_text",
          "text": full_text,
          "annotations": text_annotations,
        }],
      },
      "sequence_number": seq,
    }))
    seq += 1

    return events

  try:
    async for chunk in _parse_sse_chunks(response_stream):
        now = time.monotonic()

        # Send a keep-alive comment if too much time has passed since
        # the last event.  Prevents proxy/LB idle-timeout disconnects
        # during long-running inference (reasoning, tool use, etc.).
        if now - last_event_time >= SSE_KEEPALIVE_INTERVAL:
          yield _sse_keepalive()
          last_event_time = now

        chunk_reasoning = _get_chunk_reasoning(chunk)
        chunk_text = _get_chunk_content(chunk)
        chunk_refusal = _get_chunk_refusal(chunk)
        chunk_tools = _get_chunk_tool_calls(chunk)
        chunk_usage = _get_chunk_usage(chunk)
        fr = _get_finish_reason(chunk)

        if fr:
          finish_reason = fr

        input_tokens = chunk_usage.get("prompt_tokens", 0) or input_tokens
        output_tokens = chunk_usage.get("completion_tokens", 0) or output_tokens

        # Accumulate annotations from chunks.  Some backends send
        # citations as a top-level array (Perplexity) or on the
        # choice delta (future OpenAI streaming annotations).
        chunk_anns = _get_chunk_annotations(chunk)
        if chunk_anns:
          for ann in chunk_anns:
            if isinstance(ann, dict):
              converted = _extract_annotations({"annotations": [ann]})
              text_annotations.extend(converted)

        chunk_citations = chunk.get("citations")
        if chunk_citations and isinstance(chunk_citations, list):
          # Perplexity sends citations once; rebuild the full list
          text_annotations = _extract_annotations({"citations": chunk_citations})

        # --- Reasoning content (before text) ---
        if chunk_reasoning:
          if not reasoning_item_open:
            output_index += 1
            reasoning_id = f"rs_{shortuuid.random()}"

            # output_item.added for reasoning
            yield _sse_event("response.output_item.added", {
              "type": "response.output_item.added",
              "output_index": output_index,
              "item": {
                "type": "reasoning",
                "id": reasoning_id,
                "status": "in_progress",
                "summary": [],
              },
              "sequence_number": seq,
            })
            seq += 1

            # reasoning_summary_part.added
            yield _sse_event("response.reasoning_summary_part.added", {
              "type": "response.reasoning_summary_part.added",
              "item_id": reasoning_id,
              "output_index": output_index,
              "summary_index": 0,
              "part": {
                "type": "summary_text",
                "text": "",
              },
              "sequence_number": seq,
            })
            seq += 1

            reasoning_item_open = True

          reasoning_parts.append(chunk_reasoning)

          # reasoning_summary_text.delta
          yield _sse_event("response.reasoning_summary_text.delta", {
            "type": "response.reasoning_summary_text.delta",
            "item_id": reasoning_id,
            "output_index": output_index,
            "summary_index": 0,
            "delta": chunk_reasoning,
            "sequence_number": seq,
          })
          seq += 1
          last_event_time = time.monotonic()

        # --- Text content ---
        if chunk_text:
          # Close reasoning item before opening text item
          if reasoning_item_open:
            for evt in _close_reasoning_item():
              yield evt
            reasoning_item_open = False
          if not text_item_open:
            output_index += 1
            msg_id = f"msg_{shortuuid.random()}"

            # output_item.added
            yield _sse_event("response.output_item.added", {
              "type": "response.output_item.added",
              "output_index": output_index,
              "item": {
                "type": "message",
                "id": msg_id,
                "status": "in_progress",
                "role": "assistant",
                "content": [],
              },
              "sequence_number": seq,
            })
            seq += 1

            # content_part.added
            yield _sse_event("response.content_part.added", {
              "type": "response.content_part.added",
              "item_id": msg_id,
              "output_index": output_index,
              "content_index": 0,
              "part": {
                "type": "output_text",
                "text": "",
                "annotations": [],
              },
              "sequence_number": seq,
            })
            seq += 1

            text_item_open = True

          text_parts.append(chunk_text)

          # output_text.delta
          yield _sse_event("response.output_text.delta", {
            "type": "response.output_text.delta",
            "item_id": msg_id,
            "output_index": output_index,
            "content_index": 0,
            "delta": chunk_text,
            "logprobs": [],
            "sequence_number": seq,
          })
          seq += 1
          last_event_time = time.monotonic()

        # --- Refusal content ---
        if chunk_refusal:
          # Close reasoning item before opening refusal
          if reasoning_item_open:
            for evt in _close_reasoning_item():
              yield evt
            reasoning_item_open = False
          if not refusal_open:
            if not text_item_open:
              output_index += 1
              msg_id = f"msg_{shortuuid.random()}"

              yield _sse_event("response.output_item.added", {
                "type": "response.output_item.added",
                "output_index": output_index,
                "item": {
                  "type": "message",
                  "id": msg_id,
                  "status": "in_progress",
                  "role": "assistant",
                  "content": [],
                },
                "sequence_number": seq,
              })
              seq += 1
            else:
              # Close existing text content part before adding refusal
              for evt in _close_text_item():
                yield evt
              text_item_open = False

            # content_part.added for refusal
            refusal_content_index = 1 if text_parts else 0
            yield _sse_event("response.content_part.added", {
              "type": "response.content_part.added",
              "item_id": msg_id,
              "output_index": output_index,
              "content_index": refusal_content_index,
              "part": {
                "type": "refusal",
                "refusal": "",
              },
              "sequence_number": seq,
            })
            seq += 1
            refusal_open = True

          refusal_parts.append(chunk_refusal)

          yield _sse_event("response.refusal.delta", {
            "type": "response.refusal.delta",
            "item_id": msg_id,
            "output_index": output_index,
            "content_index": 1 if text_parts else 0,
            "delta": chunk_refusal,
            "sequence_number": seq,
          })
          seq += 1
          last_event_time = time.monotonic()

        # --- Tool calls ---
        if chunk_tools:
          for tc in chunk_tools:
            tc_index = tc.get("index", 0)
            tool_state = tool_blocks.setdefault(
              tc_index,
              {"arg_parts": [], "emitted": False},
            )

            tc_id = tc.get("id")
            tc_func = tc.get("function") or {}
            tc_name = tc_func.get("name")
            tc_args = tc_func.get("arguments") or ""

            if tc_id:
              tool_state["id"] = _to_openai_tool_id(tc_id)
            if tc_name:
              tool_state["name"] = tc_name
            if tc_args:
              tool_state["arg_parts"].append(tc_args)

            if not tool_state.get("emitted") and tool_state.get("id"):
              # Close open items before emitting tool call
              if reasoning_item_open:
                for evt in _close_reasoning_item():
                  yield evt
                reasoning_item_open = False
              if text_item_open:
                for evt in _close_text_item():
                  yield evt
                text_item_open = False

              output_index += 1
              tool_state["output_index"] = output_index
              tool_state["emitted"] = True
              call_id = tool_state["id"]

              yield _sse_event("response.output_item.added", {
                "type": "response.output_item.added",
                "output_index": output_index,
                "item": {
                  "type": "function_call",
                  "id": call_id,
                  "call_id": call_id,
                  "name": tool_state.get("name", ""),
                  "arguments": "",
                  "status": "in_progress",
                },
                "sequence_number": seq,
              })
              seq += 1

              # Emit accumulated args so far
              if tool_state["arg_parts"]:
                yield _sse_event("response.function_call_arguments.delta", {
                  "type": "response.function_call_arguments.delta",
                  "item_id": call_id,
                  "output_index": output_index,
                  "delta": "".join(tool_state["arg_parts"]),
                  "sequence_number": seq,
                })
                seq += 1
              continue

            if tc_args and tool_state.get("emitted"):
              yield _sse_event("response.function_call_arguments.delta", {
                "type": "response.function_call_arguments.delta",
                "item_id": tool_state.get("id"),
                "output_index": tool_state.get("output_index", output_index),
                "delta": tc_args,
                "sequence_number": seq,
              })
              seq += 1
          last_event_time = time.monotonic()

  except BackendError as e:
    logger.warning("Responses streaming backend error %d: %s", e.status_code, e.body[:256])
    if e.status_code == 429:
      stream_error = "Rate limit exceeded"
    elif e.status_code >= 500:
      stream_error = "Backend server error"
    else:
      stream_error = "Backend request failed"
  except Exception as e:
    logger.error("Responses stream conversion error: %s", e, exc_info=True)
    stream_error = "An internal error occurred during streaming"

  if stream_error:
    if reasoning_item_open:
      for evt in _close_reasoning_item():
        yield evt
      reasoning_item_open = False

    if not text_item_open:
      output_index += 1
      msg_id = f"msg_{shortuuid.random()}"
      yield _sse_event("response.output_item.added", {
        "type": "response.output_item.added",
        "output_index": output_index,
        "item": {
          "type": "message",
          "id": msg_id,
          "status": "in_progress",
          "role": "assistant",
          "content": [],
        },
        "sequence_number": seq,
      })
      seq += 1
      yield _sse_event("response.content_part.added", {
        "type": "response.content_part.added",
        "item_id": msg_id,
        "output_index": output_index,
        "content_index": 0,
        "part": {"type": "output_text", "text": "", "annotations": []},
        "sequence_number": seq,
      })
      seq += 1
      text_item_open = True
      text_parts = []
      text_annotations = []

    error_text = f"\n\n[Stream error: {stream_error}]"
    text_parts.append(error_text)
    yield _sse_event("response.output_text.delta", {
      "type": "response.output_text.delta",
      "item_id": msg_id,
      "output_index": output_index,
      "content_index": 0,
      "delta": error_text,
      "logprobs": [],
      "sequence_number": seq,
    })
    seq += 1

  # Close open reasoning item
  if reasoning_item_open:
    for evt in _close_reasoning_item():
      yield evt

  # Close open text item
  if text_item_open:
    for evt in _close_text_item():
      yield evt

  # Close open refusal
  if refusal_open:
    refusal_ci = 1 if text_parts else 0
    full_refusal = "".join(refusal_parts)
    yield _sse_event("response.refusal.done", {
      "type": "response.refusal.done",
      "item_id": msg_id,
      "output_index": output_index,
      "content_index": refusal_ci,
      "refusal": full_refusal,
      "sequence_number": seq,
    })
    seq += 1

    yield _sse_event("response.content_part.done", {
      "type": "response.content_part.done",
      "item_id": msg_id,
      "output_index": output_index,
      "content_index": refusal_ci,
      "part": {
        "type": "refusal",
        "refusal": full_refusal,
      },
      "sequence_number": seq,
    })
    seq += 1

    yield _sse_event("response.output_item.done", {
      "type": "response.output_item.done",
      "output_index": output_index,
      "item": {
        "type": "message",
        "id": msg_id,
        "status": "completed",
        "role": "assistant",
        "content": [{
          "type": "refusal",
          "refusal": full_refusal,
        }],
      },
      "sequence_number": seq,
    })
    seq += 1

  # Close open tool call items
  for tool_state in tool_blocks.values():
    if not tool_state.get("emitted"):
      # Deferred tool calls that never got emitted
      if tool_state.get("id"):
        output_index += 1
        tool_state["output_index"] = output_index
        call_id = tool_state["id"]

        yield _sse_event("response.output_item.added", {
          "type": "response.output_item.added",
          "output_index": output_index,
          "item": {
            "type": "function_call",
            "id": call_id,
            "call_id": call_id,
            "name": tool_state.get("name", ""),
            "arguments": "",
            "status": "in_progress",
          },
          "sequence_number": seq,
        })
        seq += 1
        if tool_state["arg_parts"]:
          yield _sse_event("response.function_call_arguments.delta", {
            "type": "response.function_call_arguments.delta",
            "item_id": call_id,
            "output_index": output_index,
            "delta": "".join(tool_state["arg_parts"]),
            "sequence_number": seq,
          })
          seq += 1
        tool_state["emitted"] = True

    if tool_state.get("emitted"):
      call_id = tool_state.get("id")
      tool_args = "".join(tool_state.get("arg_parts", []))

      # function_call_arguments.done
      yield _sse_event("response.function_call_arguments.done", {
        "type": "response.function_call_arguments.done",
        "item_id": call_id,
        "output_index": tool_state.get("output_index", output_index),
        "arguments": tool_args,
        "name": tool_state.get("name", ""),
        "sequence_number": seq,
      })
      seq += 1

      # output_item.done
      yield _sse_event("response.output_item.done", {
        "type": "response.output_item.done",
        "output_index": tool_state.get("output_index", output_index),
        "item": {
          "type": "function_call",
          "id": call_id,
          "call_id": call_id,
          "name": tool_state.get("name", ""),
          "arguments": tool_args,
          "status": "completed",
        },
        "sequence_number": seq,
      })
      seq += 1

  # Final terminal event: response.completed, response.incomplete, or response.failed
  status = _map_status(finish_reason) if finish_reason else "completed"
  if stream_error:
    status = "failed"

  final_response = {
    **skeleton,
    "status": status,
    "output": [],  # SDK reads output from output_item.done events
    "usage": _make_usage(
      input_tokens=input_tokens,
      output_tokens=output_tokens,
    ),
    "incomplete_details": {"reason": _incomplete_reason(finish_reason)} if status == "incomplete" else None,
  }

  if status == "completed":
    final_response["completed_at"] = int(time.time())

  if status == "incomplete":
    terminal_event = "response.incomplete"
  elif status == "failed":
    terminal_event = "response.failed"
  else:
    terminal_event = "response.completed"

  yield _sse_event(terminal_event, {
    "type": terminal_event,
    "sequence_number": seq,
    "response": final_response,
  })


# --- Route handler ---


@responses_compatible_routes.post("/v1/responses")
async def post_responses(request: Request, api_key: str = Depends(get_api_key)):
  request_id = f"req_{shortuuid.random()}"

  try:
    body = await request.body()
    try:
      json_body = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
      return _responses_error(400, "Invalid JSON in request body", request_id=request_id)

    # Validate required fields
    if "model" not in json_body or not json_body["model"]:
      return _responses_error(400, "model is required", request_id=request_id)

    inp = json_body.get("input")
    if inp is None:
      return _responses_error(400, "input is required", request_id=request_id)

    request_model = json_body["model"]
    is_stream = json_body.get("stream", False)
    response_id = f"resp_{shortuuid.random()}"

    logger.info(
      "Responses API request: model=%s stream=%s",
      request_model, is_stream,
    )

    # Log if client requests persistence (Harbor Boost does not persist responses)
    if json_body.get("store") is True:
      logger.debug(
        "store=true requested but Harbor Boost does not persist responses; "
        "response will have store=false"
      )

    openai_body = _build_openai_body(json_body)

    # Refresh downstream models for routing
    await mapper.list_downstream()

    # Resolve backend config via Harbor's mapper
    proxy_config = mapper.resolve_request_config(openai_body)
    proxy = llm_mod.LLM(**proxy_config)

    # Check for direct tasks
    if (
      mapper.is_direct_task(proxy)
      and proxy.workflow is None
      and proxy.boost_params.get("workflow") is None
    ):
      logger.debug("Responses request routed as direct task: model=%s", request_model)
      result = await proxy.chat_completion()
      response = _build_responses_response(result, request_model, response_id, request_body=json_body)
      logger.info("Responses API response: model=%s status=%s", request_model, response.get("status"))
      return JSONResponse(
        content=response,
        status_code=200,
        headers={OPENAI_REQUEST_ID_HEADER: request_id},
      )

    completion = await proxy.serve()

    if completion is None:
      return _responses_error(500, "No completion returned", request_id=request_id)

    if is_stream:
      logger.debug("Starting Responses streaming response: model=%s", request_model)
      return StreamingResponse(
        _responses_stream_converter(completion, request_model, response_id, request_body=json_body),
        media_type="text/event-stream",
        headers={**SSE_HEADERS, OPENAI_REQUEST_ID_HEADER: request_id},
      )
    else:
      result = await proxy.consume_stream(completion)
      response = _build_responses_response(result, request_model, response_id, request_body=json_body)
      logger.info("Responses API response: model=%s status=%s", request_model, response.get("status"))
      return JSONResponse(
        content=response,
        status_code=200,
        headers={OPENAI_REQUEST_ID_HEADER: request_id},
      )

  except BackendError as e:
    # Forward rate-limit / retry headers from the backend so the SDK
    # can implement automatic retries with the correct backoff.
    logger.warning("Responses handler backend error %d: %s", e.status_code, e.body[:256])
    status = e.status_code
    if status == 429:
      detail = "Rate limit exceeded"
    elif status >= 500:
      detail = "Backend server error"
    else:
      detail = "Backend request failed"
    resp = _responses_error(status, detail, request_id=request_id)
    for hdr, val in e.headers.items():
      if hdr in RATE_LIMIT_FORWARD_HEADERS:
        resp.headers[hdr] = val
    return resp
  except HTTPException as e:
    # Sanitize 5xx error details to avoid leaking internal information
    detail = str(e.detail) if e.status_code < 500 else "Internal server error"
    if e.status_code >= 500:
      logger.error("Responses handler HTTPException %d: %s", e.status_code, e.detail)
    return _responses_error(e.status_code, detail, request_id=request_id)
  except ValueError as e:
    # Log the full error but only surface a safe message to the client.
    # ValueError from mapper (e.g. missing model specifier) may contain
    # internal details we don't want to leak.
    logger.warning("Responses handler validation error: %s", e)
    return _responses_error(400, "Invalid request: could not resolve model or parameters", request_id=request_id)
  except Exception as e:
    logger.error("Responses handler unexpected error: %s", e, exc_info=True)
    return _responses_error(500, "Internal server error", request_id=request_id)


# --- Stub endpoints ---
#
# Harbor Boost does not persist responses (store is always false), so
# retrieval, deletion, and cancellation endpoints return informative
# errors explaining why the operation cannot succeed.

_RESPONSE_NOT_FOUND = (
  "Response {response_id} not found. Harbor Boost does not persist "
  "responses (store is always false). To get results, consume them "
  "directly from the POST /v1/responses response or stream."
)

_RESPONSE_CANCEL_NOT_FOUND = (
  "Response {response_id} cannot be cancelled. Harbor Boost does not "
  "persist or track in-flight responses. Cancel the HTTP request "
  "or close the streaming connection instead."
)

_RESPONSE_DELETE_NOT_FOUND = (
  "Response {response_id} cannot be deleted. Harbor Boost does not "
  "persist responses (store is always false), so there is nothing to delete."
)


@responses_compatible_routes.get("/v1/responses/{response_id}")
async def get_response(response_id: str, api_key: str = Depends(get_api_key)):
  request_id = f"req_{shortuuid.random()}"
  return _responses_error(
    404, _RESPONSE_NOT_FOUND.format(response_id=response_id),
    error_code="not_found", request_id=request_id,
  )


@responses_compatible_routes.delete("/v1/responses/{response_id}")
async def delete_response(response_id: str, api_key: str = Depends(get_api_key)):
  request_id = f"req_{shortuuid.random()}"
  return _responses_error(
    404, _RESPONSE_DELETE_NOT_FOUND.format(response_id=response_id),
    error_code="not_found", request_id=request_id,
  )


@responses_compatible_routes.post("/v1/responses/{response_id}/cancel")
async def cancel_response(response_id: str, api_key: str = Depends(get_api_key)):
  request_id = f"req_{shortuuid.random()}"
  return _responses_error(
    404, _RESPONSE_CANCEL_NOT_FOUND.format(response_id=response_id),
    error_code="not_found", request_id=request_id,
  )
