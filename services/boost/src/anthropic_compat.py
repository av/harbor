from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, StreamingResponse

import json

import dotty
import format
import log
import shortuuid
import mapper
import llm as llm_mod
from auth import get_api_key
from compat_utils import (
    ANTHROPIC_VERSION,
    ANTHROPIC_VERSION_HEADER,
    REQUEST_ID_HEADER,
    get_chunk_content as _get_chunk_content,
    get_chunk_reasoning as _get_chunk_reasoning,
    get_chunk_tool_calls as _get_chunk_tool_calls,
    get_chunk_usage as _get_chunk_usage,
    sse_event as _sse_event,
    to_anthropic_tool_id as _to_anthropic_tool_id,
    to_openai_tool_id as _to_openai_tool_id,
)

logger = log.setup_logger(__name__)
anthropic_compatible_routes = APIRouter()

ERROR_TYPE_MAP = {
  400: "invalid_request_error",
  401: "authentication_error",
  403: "permission_error",
  404: "not_found_error",
  429: "rate_limit_error",
  500: "api_error",
  529: "overloaded_error",
}


def _anthropic_headers(request_id=None):
  """Build standard Anthropic response headers."""
  headers = {ANTHROPIC_VERSION_HEADER: ANTHROPIC_VERSION}
  if request_id:
    headers[REQUEST_ID_HEADER] = request_id
  return headers


def _anthropic_error(status_code, message, error_type=None, request_id=None):
  if error_type is None:
    error_type = ERROR_TYPE_MAP.get(status_code, "api_error")
  return JSONResponse(
    status_code=status_code,
    content={"type": "error", "error": {"type": error_type, "message": message}},
    headers=_anthropic_headers(request_id),
  )


# --- Beta flags ---

def _parse_beta_flags(request: Request):
  """Parse the anthropic-beta request header and log recognized flags.

  The Anthropic SDK sends a comma-separated list of beta feature flags
  (e.g. ``"max-tokens-3-5-sonnet-2024-07-15,prompt-caching-2024-07-31"``).
  The compat layer accepts these without error for SDK compatibility.
  No flags change behavior — they are logged for observability only.
  """
  raw = request.headers.get("anthropic-beta")
  if not raw:
    return []

  flags = [f.strip() for f in raw.split(",") if f.strip()]
  if flags:
    logger.debug("anthropic-beta flags: %s", ", ".join(flags))
  return flags


# --- Auth ---

def _synthesize_authorization(request: Request):
  """Convert x-api-key header to Authorization header if needed.
  Mutates request.scope so downstream code sees a standard Authorization header."""
  auth_header_val = request.headers.get("authorization")
  api_key = request.headers.get("x-api-key")

  if not auth_header_val and api_key:
    synthesized = f"Bearer {api_key}"
    scope = request.scope
    raw_headers = list(scope.get("headers", []))
    raw_headers.append((b"authorization", synthesized.encode()))
    scope["headers"] = raw_headers
    if hasattr(request, "_headers"):
      del request._headers


# --- Request validation and conversion ---

def _validate_request(body: dict, request_id=None):
  if "model" not in body or not body["model"]:
    return _anthropic_error(400, "model is required", request_id=request_id)

  if "max_tokens" not in body:
    return _anthropic_error(400, "max_tokens is required", request_id=request_id)

  messages = body.get("messages")
  if not messages or not isinstance(messages, list) or len(messages) == 0:
    return _anthropic_error(400, "messages must be a non-empty array", request_id=request_id)

  for msg in messages:
    if msg.get("role") == "system":
      return _anthropic_error(
        400,
        'messages containing role "system" are not allowed; use top-level system parameter',
        request_id=request_id,
      )

  return None


def _convert_messages(body: dict):
  """Convert Anthropic messages to OpenAI format.

  Anthropic content blocks may carry ``cache_control`` directives (e.g.
  ``{"type": "ephemeral"}``).  These are intentionally stripped during
  conversion because OpenAI-compatible backends do not support prompt
  caching via inline annotations — only the ``text`` / ``image`` / tool
  payload is extracted from each block.
  """
  openai_messages = []

  system = body.get("system")
  if system:
    if isinstance(system, str):
      openai_messages.append({"role": "system", "content": system})
    elif isinstance(system, list):
      # Only text is extracted; cache_control and other block-level
      # metadata are intentionally dropped.
      text_parts = [
        block.get("text", "")
        for block in system
        if isinstance(block, dict) and block.get("type") == "text"
      ]
      if text_parts:
        openai_messages.append({"role": "system", "content": "\n".join(text_parts)})

  for msg in body.get("messages", []):
    role = msg.get("role")
    content = msg.get("content")

    if role == "user":
      openai_messages.extend(_convert_user_message(content))
    elif role == "assistant":
      openai_messages.extend(_convert_assistant_message(content))

  return openai_messages


def _convert_user_message(content):
  if isinstance(content, str):
    return [{"role": "user", "content": content}]

  if not isinstance(content, list):
    return [{"role": "user", "content": str(content)}]

  openai_parts = []
  tool_results = []

  for block in content:
    block_type = block.get("type")

    if block_type == "text":
      openai_parts.append({"type": "text", "text": block.get("text", "")})
    elif block_type == "image":
      source = block.get("source", {})
      source_type = source.get("type", "base64")
      if source_type == "url":
        url = source.get("url", "")
        openai_parts.append(
          {"type": "image_url", "image_url": {"url": url}}
        )
      else:
        # base64 source (default)
        media_type = source.get("media_type", "image/png")
        data = source.get("data", "")
        openai_parts.append(
          {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{data}"}}
        )
    elif block_type == "document":
      # Anthropic document blocks (PDFs, etc.) — extract text content if
      # available, otherwise pass the base64 data as-is for backends that
      # may support it. Most OpenAI-compatible backends don't support
      # inline PDFs, so we log a warning and do best-effort.
      source = block.get("source", {})
      source_type = source.get("type", "base64")
      if source_type == "url":
        url = source.get("url", "")
        logger.warning("Document URL content blocks are not fully supported; passing URL as text")
        openai_parts.append({"type": "text", "text": f"[Document: {url}]"})
      else:
        media_type = source.get("media_type", "application/pdf")
        data = source.get("data", "")
        # Some backends (e.g., OpenAI GPT-4o) accept PDFs as images
        if media_type.startswith("image/"):
          openai_parts.append(
            {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{data}"}}
          )
        else:
          logger.warning(
            "Document content block (media_type=%s) has limited backend support; "
            "passing as text placeholder", media_type
          )
          openai_parts.append({"type": "text", "text": f"[Document: {media_type}]"})
    elif block_type == "tool_result":
      tool_content = block.get("content", "")
      if isinstance(tool_content, list):
        text_parts = [
          b.get("text", "")
          for b in tool_content
          if isinstance(b, dict) and b.get("type") == "text"
        ]
        tool_content = "\n".join(text_parts)
      raw_tool_use_id = block.get("tool_use_id", "")
      tool_results.append(
        {
          "role": "tool",
          "tool_call_id": _to_openai_tool_id(raw_tool_use_id) if raw_tool_use_id else "",
          "content": str(tool_content),
        }
      )

  messages = list(tool_results)
  if openai_parts:
    if len(openai_parts) == 1 and openai_parts[0].get("type") == "text":
      messages.append({"role": "user", "content": openai_parts[0]["text"]})
    else:
      messages.append({"role": "user", "content": openai_parts})

  return messages


def _convert_assistant_message(content):
  if isinstance(content, str):
    return [{"role": "assistant", "content": content}]

  if not isinstance(content, list):
    return [{"role": "assistant", "content": str(content)}]

  text_parts = []
  tool_calls = []

  for block in content:
    block_type = block.get("type")

    if block_type == "text":
      text_parts.append(block.get("text", ""))
    elif block_type == "tool_use":
      raw_id = block.get("id", "")
      tool_calls.append(
        {
          "id": _to_openai_tool_id(raw_id) if raw_id else "",
          "type": "function",
          "function": {
            "name": block.get("name", ""),
            "arguments": json.dumps(block.get("input", {})),
          },
        }
      )
    # Skip thinking blocks — no OpenAI equivalent for conversation history

  msg = {"role": "assistant"}
  if text_parts:
    msg["content"] = "\n".join(text_parts)
  else:
    msg["content"] = None

  if tool_calls:
    msg["tool_calls"] = tool_calls

  return [msg]


def _convert_params(body: dict):
  params = {}

  max_tokens = body.get("max_tokens", 0)
  thinking = body.get("thinking")

  if thinking and isinstance(thinking, dict) and thinking.get("type") == "enabled":
    budget_tokens = thinking.get("budget_tokens", 0)
    # Map to max_completion_tokens which covers both reasoning + output
    params["max_completion_tokens"] = budget_tokens + max_tokens
  elif max_tokens:
    params["max_tokens"] = max_tokens

  if "temperature" in body:
    params["temperature"] = body["temperature"]
  if "top_p" in body:
    params["top_p"] = body["top_p"]
  if "top_k" in body:
    # Best-effort passthrough — some OpenAI-compatible backends (vLLM, Ollama,
    # llama.cpp) accept top_k; others silently ignore it.
    params["top_k"] = body["top_k"]
  if "stop_sequences" in body:
    params["stop"] = body["stop_sequences"]
  if body.get("stream"):
    params["stream"] = True
    params["stream_options"] = {"include_usage": True}

  return params


def _convert_tools(body: dict):
  tools = body.get("tools")
  if not tools:
    return []

  return [
    {
      "type": "function",
      "function": {
        "name": tool.get("name", ""),
        "description": tool.get("description", ""),
        "parameters": tool.get("input_schema", {}),
      },
    }
    for tool in tools
  ]


def _convert_tool_choice(body: dict):
  tc = body.get("tool_choice")
  if not tc:
    return None

  tc_type = tc.get("type")
  if tc_type == "auto":
    return "auto"
  elif tc_type == "any":
    return "required"
  elif tc_type == "none":
    return "none"
  elif tc_type == "tool":
    return {"type": "function", "function": {"name": tc.get("name", "")}}

  return None


def _build_openai_body(body: dict):
  openai_body = {
    "model": body["model"],
    "messages": _convert_messages(body),
    **_convert_params(body),
  }

  tools = _convert_tools(body)
  if tools:
    openai_body["tools"] = tools

  tool_choice = _convert_tool_choice(body)
  if tool_choice is not None:
    openai_body["tool_choice"] = tool_choice

  return openai_body


# --- Response building ---

def _map_stop_reason(finish_reason, stop_sequences=None, content_text=None):
  if finish_reason == "length":
    return "max_tokens", None

  if finish_reason == "tool_calls":
    return "tool_use", None

  if finish_reason == "stop" and stop_sequences:
    # OpenAI backends return finish_reason "stop" for both natural end-of-turn
    # and stop sequence hits.  Check if the generated text ends with any of
    # the requested stop sequences to disambiguate.
    if content_text:
      stripped = content_text.rstrip()
      for seq in stop_sequences:
        if stripped.endswith(seq):
          return "stop_sequence", seq

    # No content or no match — the model ended naturally despite stop_sequences
    # being configured.  Report end_turn, not stop_sequence.
    return "end_turn", None

  return "end_turn", None


def _parse_tool_call_arguments(arguments):
  try:
    parsed_arguments = json.loads(arguments)
  except (json.JSONDecodeError, TypeError):
    return {}

  return parsed_arguments if isinstance(parsed_arguments, dict) else {}


def _build_content_blocks(openai_result):
  blocks = []

  # Check for reasoning/thinking content — emitted before text
  message = dotty.get(openai_result, "choices.0.message", {})
  reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
  if reasoning:
    blocks.append(
      {
        "type": "thinking",
        "thinking": str(reasoning),
      }
    )

  content = dotty.get(openai_result, "choices.0.message.content")
  if content:
    blocks.append(
      {
        "type": "text",
        "text": format.clean_text_preserve_newlines(str(content)),
      }
    )

  tool_calls = dotty.get(openai_result, "choices.0.message.tool_calls", [])
  for tc in tool_calls:
    parsed_input = _parse_tool_call_arguments(
      tc.get("function", {}).get("arguments", "{}")
    )

    raw_id = tc.get("id") or f"toolu_{shortuuid.random()}"
    blocks.append(
      {
        "type": "tool_use",
        "id": _to_anthropic_tool_id(raw_id),
        "name": tc.get("function", {}).get("name", ""),
        "input": parsed_input,
      }
    )

  if not blocks:
    blocks.append({"type": "text", "text": ""})

  return blocks


def _build_anthropic_response(openai_result, request_model, stop_sequences=None):
  finish_reason = dotty.get(openai_result, "choices.0.finish_reason", "stop")
  content_blocks = _build_content_blocks(openai_result)
  has_visible_tool_use = any(
    block.get("type") == "tool_use" for block in content_blocks
  )
  if finish_reason == "tool_calls" and not has_visible_tool_use:
    finish_reason = "stop"
  content_text = content_blocks[0].get("text", "") if content_blocks else ""
  stop_reason, stop_sequence = _map_stop_reason(
    finish_reason, stop_sequences, content_text
  )

  usage = dotty.get(openai_result, "usage", {})

  response = {
    "type": "message",
    "id": f"msg_{shortuuid.random()}",
    "role": "assistant",
    "model": request_model,
    "content": content_blocks,
    "stop_reason": stop_reason,
    "stop_sequence": stop_sequence,
    "usage": {
      "input_tokens": usage.get("prompt_tokens", 0),
      "output_tokens": usage.get("completion_tokens", 0),
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 0,
    },
  }

  return response


# --- Streaming conversion ---

async def _anthropic_stream_converter(
  response_stream, request_model, stop_sequences=None
):
  """Convert Harbor Boost's OpenAI-format SSE stream to Anthropic SSE events.

  Harbor's LLM.response_stream() yields stringified SSE chunks in the form
  ``data: {...}\n\n`` or ``data: [DONE]``. This generator parses those chunks
  and re-emits them as Anthropic-format SSE events.
  """
  msg_id = f"msg_{shortuuid.random()}"
  block_index = -1
  thinking_block_open = False
  text_block_open = False
  tool_blocks = {}
  input_tokens = 0
  output_tokens = 0
  finish_reason = None
  accumulated_text = ""
  has_visible_tool_use = False

  yield _sse_event(
    "message_start",
    {
      "type": "message_start",
      "message": {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "model": request_model,
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
      },
    },
  )

  # Ping to signal the connection is alive and streaming has begun.
  # Some clients or proxies close connections that receive no data
  # for a while; this single early ping avoids that scenario.
  yield _sse_event("ping", {})

  stream_error = None

  try:
    async for raw_chunk in response_stream:
      chunk_str = raw_chunk if isinstance(raw_chunk, str) else raw_chunk.decode("utf-8")

      for line in chunk_str.strip().split("\n"):
        line = line.strip()
        if not line or line == "data: [DONE]" or not line.startswith("data: "):
          continue

        try:
          chunk = json.loads(line[6:])
        except (json.JSONDecodeError, TypeError):
          continue

        text_content = _get_chunk_content(chunk)
        reasoning_content = _get_chunk_reasoning(chunk)
        tool_calls = _get_chunk_tool_calls(chunk)
        chunk_usage = _get_chunk_usage(chunk)
        fr = dotty.get(chunk, "choices.0.finish_reason")

        if fr:
          finish_reason = fr

        input_tokens = chunk_usage.get("prompt_tokens", 0) or input_tokens
        output_tokens = chunk_usage.get("completion_tokens", 0) or output_tokens

        # Reasoning/thinking content — emitted as thinking blocks before text
        if reasoning_content:
          if not thinking_block_open:
            block_index += 1
            yield _sse_event(
              "content_block_start",
              {
                "type": "content_block_start",
                "index": block_index,
                "content_block": {"type": "thinking", "thinking": ""},
              },
            )
            thinking_block_open = True
          yield _sse_event(
            "content_block_delta",
            {
              "type": "content_block_delta",
              "index": block_index,
              "delta": {"type": "thinking_delta", "thinking": reasoning_content},
            },
          )

        if text_content:
          accumulated_text += text_content
          # Close thinking block before opening text block
          if thinking_block_open:
            yield _sse_event(
              "content_block_stop",
              {
                "type": "content_block_stop",
                "index": block_index,
              },
            )
            thinking_block_open = False
          if not text_block_open:
            block_index += 1
            yield _sse_event(
              "content_block_start",
              {
                "type": "content_block_start",
                "index": block_index,
                "content_block": {"type": "text", "text": ""},
              },
            )
            text_block_open = True
          yield _sse_event(
            "content_block_delta",
            {
              "type": "content_block_delta",
              "index": block_index,
              "delta": {"type": "text_delta", "text": text_content},
            },
          )

        if tool_calls:
          for tc in tool_calls:
            tc_index = tc.get("index", 0)
            tool_state = tool_blocks.setdefault(
              tc_index,
              {
                "arguments": "",
                "emitted": False,
              },
            )

            tc_id = tc.get("id")
            tc_name = dotty.get(tc, "function.name")
            tc_args = dotty.get(tc, "function.arguments", "")

            if tc_id:
              tool_state["id"] = _to_anthropic_tool_id(tc_id)
            if tc_name:
              tool_state["name"] = tc_name
            if tc_args:
              tool_state["arguments"] += tc_args

            if not tool_state.get("emitted") and tool_state.get("id"):
              if thinking_block_open:
                yield _sse_event(
                  "content_block_stop",
                  {
                    "type": "content_block_stop",
                    "index": block_index,
                  },
                )
                thinking_block_open = False
              if text_block_open:
                yield _sse_event(
                  "content_block_stop",
                  {
                    "type": "content_block_stop",
                    "index": block_index,
                  },
                )
                text_block_open = False
              block_index += 1
              tool_state["block_index"] = block_index
              tool_state["emitted"] = True
              has_visible_tool_use = True
              yield _sse_event(
                "content_block_start",
                {
                  "type": "content_block_start",
                  "index": block_index,
                  "content_block": {
                    "type": "tool_use",
                    "id": tool_state.get("id"),
                    "name": tool_state.get("name", ""),
                    "input": {},
                  },
                },
              )
              if tool_state.get("arguments"):
                yield _sse_event(
                  "content_block_delta",
                  {
                    "type": "content_block_delta",
                    "index": block_index,
                    "delta": {
                      "type": "input_json_delta",
                      "partial_json": tool_state.get("arguments", ""),
                    },
                  },
                )
              continue

            if tc_args and tool_state.get("emitted"):
              yield _sse_event(
                "content_block_delta",
                {
                  "type": "content_block_delta",
                  "index": tool_state.get("block_index", block_index),
                  "delta": {"type": "input_json_delta", "partial_json": tc_args},
                },
              )
  except Exception as e:
    logger.error(f"Error during stream conversion: {e}", exc_info=True)
    stream_error = str(e)

    # Close thinking block before emitting error text
    if thinking_block_open:
      yield _sse_event(
        "content_block_stop",
        {
          "type": "content_block_stop",
          "index": block_index,
        },
      )
      thinking_block_open = False

    # Emit an error as a text block so the client sees it
    if not text_block_open:
      block_index += 1
      yield _sse_event(
        "content_block_start",
        {
          "type": "content_block_start",
          "index": block_index,
          "content_block": {"type": "text", "text": ""},
        },
      )
      text_block_open = True
    yield _sse_event(
      "content_block_delta",
      {
        "type": "content_block_delta",
        "index": block_index,
        "delta": {"type": "text_delta", "text": f"\n\n[Stream error: {stream_error}]"},
      },
    )

  # Close thinking block if still open
  if thinking_block_open:
    yield _sse_event(
      "content_block_stop",
      {
        "type": "content_block_stop",
        "index": block_index,
      },
    )
    thinking_block_open = False

  # Flush any deferred tool blocks that were never emitted during streaming
  for tool_state in tool_blocks.values():
    if tool_state.get("emitted"):
      continue

    if not tool_state.get("id"):
      continue

    if text_block_open:
      yield _sse_event(
        "content_block_stop",
        {
          "type": "content_block_stop",
          "index": block_index,
        },
      )
      text_block_open = False

    block_index += 1
    tool_state["block_index"] = block_index
    tool_state["emitted"] = True
    has_visible_tool_use = True
    yield _sse_event(
      "content_block_start",
      {
        "type": "content_block_start",
        "index": block_index,
        "content_block": {
          "type": "tool_use",
          "id": tool_state.get("id"),
          "name": tool_state.get("name", ""),
          "input": {},
        },
      },
    )
    if tool_state.get("arguments"):
      yield _sse_event(
        "content_block_delta",
        {
          "type": "content_block_delta",
          "index": block_index,
          "delta": {
            "type": "input_json_delta",
            "partial_json": tool_state.get("arguments", ""),
          },
        },
      )

  # Close open content blocks
  if text_block_open:
    yield _sse_event(
      "content_block_stop",
      {
        "type": "content_block_stop",
        "index": block_index,
      },
    )

  for tool_state in tool_blocks.values():
    if not tool_state.get("emitted"):
      continue
    yield _sse_event(
      "content_block_stop",
      {
        "type": "content_block_stop",
        "index": tool_state["block_index"],
      },
    )

  # Final message_delta and message_stop
  effective_finish_reason = finish_reason or "stop"
  if effective_finish_reason == "tool_calls" and not has_visible_tool_use:
    effective_finish_reason = "stop"

  stop_reason, stop_sequence = _map_stop_reason(
    effective_finish_reason, stop_sequences, accumulated_text
  )

  yield _sse_event(
    "message_delta",
    {
      "type": "message_delta",
      "delta": {
        "stop_reason": stop_reason,
        "stop_sequence": stop_sequence,
      },
      "usage": {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
      },
    },
  )

  yield _sse_event("message_stop", {"type": "message_stop"})


# --- Route handlers ---

@anthropic_compatible_routes.post("/v1/messages")
async def post_messages(request: Request, api_key: str = Depends(get_api_key)):
  request_id = f"req_{shortuuid.random()}"

  try:
    _synthesize_authorization(request)
    _parse_beta_flags(request)

    body = await request.body()
    try:
      json_body = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
      return _anthropic_error(400, "Invalid JSON in request body", request_id=request_id)

    validation_error = _validate_request(json_body, request_id=request_id)
    if validation_error:
      return validation_error

    request_model = json_body["model"]
    stop_sequences = json_body.get("stop_sequences")
    is_stream = json_body.get("stream", False)
    openai_body = _build_openai_body(json_body)

    # Refresh downstream models to ensure routing works
    await mapper.list_downstream()

    # Resolve backend config via Harbor's mapper
    proxy_config = mapper.resolve_request_config(openai_body)
    proxy = llm_mod.LLM(**proxy_config)

    # Check for direct tasks (title generation, etc.)
    if (
      mapper.is_direct_task(proxy)
      and proxy.workflow is None
      and proxy.boost_params.get("workflow") is None
    ):
      result = await proxy.chat_completion()
      response = _build_anthropic_response(result, request_model, stop_sequences)
      return JSONResponse(
        content=response,
        status_code=200,
        headers=_anthropic_headers(request_id),
      )

    completion = await proxy.serve()

    if completion is None:
      return _anthropic_error(500, "No completion returned", request_id=request_id)

    if is_stream:
      return StreamingResponse(
        _anthropic_stream_converter(completion, request_model, stop_sequences),
        media_type="text/event-stream",
        headers=_anthropic_headers(request_id),
      )
    else:
      result = await proxy.consume_stream(completion)
      response = _build_anthropic_response(result, request_model, stop_sequences)
      return JSONResponse(
        content=response,
        status_code=200,
        headers=_anthropic_headers(request_id),
      )

  except HTTPException as e:
    error_type = ERROR_TYPE_MAP.get(e.status_code, "api_error")
    return _anthropic_error(e.status_code, e.detail, error_type, request_id=request_id)
  except ValueError as e:
    return _anthropic_error(400, str(e), request_id=request_id)
  except Exception as e:
    logger.error(f"Unexpected error in anthropic handler: {e}", exc_info=True)
    return _anthropic_error(500, "Internal server error", request_id=request_id)


@anthropic_compatible_routes.post("/v1/messages/count_tokens")
async def post_count_tokens(request: Request, api_key: str = Depends(get_api_key)):
  request_id = f"req_{shortuuid.random()}"

  try:
    _synthesize_authorization(request)
    _parse_beta_flags(request)

    body = await request.body()
    try:
      json_body = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
      return _anthropic_error(400, "Invalid JSON in request body", request_id=request_id)

    if "model" not in json_body or not json_body["model"]:
      return _anthropic_error(400, "model is required", request_id=request_id)

    messages = json_body.get("messages")
    if not messages or not isinstance(messages, list) or len(messages) == 0:
      return _anthropic_error(400, "messages must be a non-empty array", request_id=request_id)

    openai_body = _build_openai_body(
      {**json_body, "max_tokens": 1, "stream": False}
    )

    await mapper.list_downstream()

    proxy_config = mapper.resolve_request_config(openai_body)
    proxy = llm_mod.LLM(**proxy_config)

    completion = await proxy.serve()

    if completion is None:
      return _anthropic_error(500, "No completion returned", request_id=request_id)

    result = await proxy.consume_stream(completion)
    usage = dotty.get(result, "usage", {})
    input_tokens = usage.get("prompt_tokens", 0)

    return JSONResponse(
      content={"input_tokens": input_tokens},
      status_code=200,
      headers=_anthropic_headers(request_id),
    )

  except HTTPException as e:
    error_type = ERROR_TYPE_MAP.get(e.status_code, "api_error")
    return _anthropic_error(e.status_code, e.detail, error_type, request_id=request_id)
  except ValueError as e:
    return _anthropic_error(400, str(e), request_id=request_id)
  except Exception as e:
    logger.error(f"Unexpected error in count_tokens handler: {e}", exc_info=True)
    return _anthropic_error(500, "Internal server error", request_id=request_id)


# --- Message Batches stubs ---

_BATCHES_NOT_SUPPORTED = "Message batches are not supported by Harbor Boost"


@anthropic_compatible_routes.post("/v1/messages/batches")
async def create_message_batch(request: Request, api_key: str = Depends(get_api_key)):
  request_id = f"req_{shortuuid.random()}"
  return _anthropic_error(501, _BATCHES_NOT_SUPPORTED, "not_supported_error", request_id=request_id)


@anthropic_compatible_routes.get("/v1/messages/batches")
async def list_message_batches(request: Request, api_key: str = Depends(get_api_key)):
  request_id = f"req_{shortuuid.random()}"
  return _anthropic_error(501, _BATCHES_NOT_SUPPORTED, "not_supported_error", request_id=request_id)


@anthropic_compatible_routes.get("/v1/messages/batches/{batch_id}")
async def get_message_batch(batch_id: str, request: Request, api_key: str = Depends(get_api_key)):
  request_id = f"req_{shortuuid.random()}"
  return _anthropic_error(404, f"Batch {batch_id} not found", request_id=request_id)


@anthropic_compatible_routes.get("/v1/messages/batches/{batch_id}/results")
async def get_message_batch_results(batch_id: str, request: Request, api_key: str = Depends(get_api_key)):
  request_id = f"req_{shortuuid.random()}"
  return _anthropic_error(404, f"Batch {batch_id} not found", request_id=request_id)


@anthropic_compatible_routes.post("/v1/messages/batches/{batch_id}/cancel")
async def cancel_message_batch(batch_id: str, request: Request, api_key: str = Depends(get_api_key)):
  request_id = f"req_{shortuuid.random()}"
  return _anthropic_error(404, f"Batch {batch_id} not found", request_id=request_id)
