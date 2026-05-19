from fastapi import APIRouter, HTTPException, Request, Depends, Security
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security.api_key import APIKeyHeader

import json
import time

import dotty
import format
import shortuuid
import log
import mapper
import llm as llm_mod
import config

logger = log.setup_logger(__name__)
responses_compatible_routes = APIRouter()

auth_header = APIKeyHeader(name="Authorization", auto_error=False)


async def get_api_key(api_key_header: str = Security(auth_header)):
  if len(config.BOOST_AUTH) == 0:
    return

  if api_key_header is not None:
    value = api_key_header.replace("Bearer ", "").replace("bearer ", "")
    if value in config.BOOST_AUTH:
      return value

  raise HTTPException(status_code=403, detail="Unauthorized")


def _responses_error(status_code, message, error_type=None, error_code=None):
  if error_type is None:
    error_type = {
      400: "invalid_request_error",
      401: "authentication_error",
      403: "permission_error",
      404: "not_found_error",
      429: "rate_limit_error",
      500: "server_error",
    }.get(status_code, "server_error")
  body = {
    "error": {
      "message": message,
      "type": error_type,
      "param": None,
      "code": error_code,
    }
  }
  return JSONResponse(status_code=status_code, content=body)


def _make_usage(input_tokens=0, output_tokens=0, total_tokens=None):
  """Build a usage dict with the token detail sub-objects the SDK requires."""
  if total_tokens is None:
    total_tokens = input_tokens + output_tokens
  return {
    "input_tokens": input_tokens,
    "output_tokens": output_tokens,
    "total_tokens": total_tokens,
    "input_tokens_details": {"cached_tokens": 0},
    "output_tokens_details": {"reasoning_tokens": 0},
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

    elif item_type == "function_call_output":
      messages.append({
        "role": "tool",
        "tool_call_id": item.get("call_id", ""),
        "content": item.get("output", ""),
      })

    elif item_type == "item_reference":
      # References to previous response items; skip in translation
      pass

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
      if image_url:
        openai_parts.append({
          "type": "image_url",
          "image_url": {"url": image_url},
        })
      else:
        # Base64 image
        detail = part.get("detail", "auto")
        file_id = part.get("file_id", "")
        if file_id:
          openai_parts.append({
            "type": "image_url",
            "image_url": {"url": file_id, "detail": detail},
          })

    elif part_type == "input_audio":
      data = part.get("data", "")
      fmt = part.get("format", "wav")
      openai_parts.append({
        "type": "input_audio",
        "input_audio": {"data": data, "format": fmt},
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


def _convert_tools(body: dict):
  """Convert Responses API tools to Chat Completions tools format."""
  tools = body.get("tools")
  if not tools:
    return []

  openai_tools = []
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
    # web_search, file_search, code_interpreter are OpenAI-hosted
    # tools that we can't replicate; skip them silently
  return openai_tools


def _convert_tool_choice(body: dict):
  """Convert Responses API tool_choice to Chat Completions tool_choice."""
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

  if body.get("stream", False):
    openai_body["stream"] = True
    openai_body["stream_options"] = {"include_usage": True}

  tools = _convert_tools(body)
  if tools:
    openai_body["tools"] = tools

  tool_choice = _convert_tool_choice(body)
  if tool_choice is not None:
    openai_body["tool_choice"] = tool_choice

  return openai_body


# --- Response conversion (Chat Completions -> Responses) ---


def _build_output_items(openai_result):
  """Convert Chat Completions result to Responses API output items."""
  output = []

  content = dotty.get(openai_result, "choices.0.message.content")
  tool_calls = dotty.get(openai_result, "choices.0.message.tool_calls", [])

  if content:
    output.append({
      "type": "message",
      "id": f"msg_{shortuuid.random()}",
      "status": "completed",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": format.clean_text_preserve_newlines(str(content)),
          "annotations": [],
        }
      ],
    })

  for tc in tool_calls:
    func = tc.get("function", {})
    tc_id = tc.get("id", f"call_{shortuuid.random()}")
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
  return "completed"


def _build_responses_response(openai_result, request_model, response_id):
  """Build a full Responses API response object."""
  finish_reason = dotty.get(openai_result, "choices.0.finish_reason", "stop")
  usage = dotty.get(openai_result, "usage", {})
  output = _build_output_items(openai_result)
  status = _map_status(finish_reason)

  return {
    "id": response_id,
    "object": "response",
    "created_at": int(time.time()),
    "status": status,
    "model": request_model,
    "output": output,
    "usage": _make_usage(
      input_tokens=usage.get("prompt_tokens", 0),
      output_tokens=usage.get("completion_tokens", 0),
      total_tokens=usage.get("total_tokens", 0),
    ),
    "metadata": {},
    "temperature": None,
    "top_p": None,
    "max_output_tokens": None,
    "truncation": "disabled",
    "tool_choice": "auto",
    "tools": [],
    "text": {
      "format": {"type": "text"},
    },
    "parallel_tool_calls": True,
    "error": None,
    "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
  }


# --- SSE helpers ---


def _sse_event(event_type, data):
  return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


# --- Chunk utilities (standalone) ---


def _get_chunk_content(chunk):
  return dotty.get(chunk, "choices.0.delta.content", "")


def _get_chunk_tool_calls(chunk):
  return dotty.get(chunk, "choices.0.delta.tool_calls", [])


def _get_chunk_usage(chunk):
  return dotty.get(chunk, "usage") or {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
  }


# --- Streaming conversion ---


async def _responses_stream_converter(
  response_stream, request_model, response_id
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
  text_item_open = False
  text_content = ""
  msg_id = None
  tool_blocks = {}
  input_tokens = 0
  output_tokens = 0
  finish_reason = None

  # Skeleton response for the created event
  skeleton = {
    "id": response_id,
    "object": "response",
    "created_at": created_at,
    "status": "in_progress",
    "model": request_model,
    "output": [],
    "usage": _make_usage(),
    "metadata": {},
    "temperature": None,
    "top_p": None,
    "max_output_tokens": None,
    "truncation": "disabled",
    "tool_choice": "auto",
    "tools": [],
    "text": {"format": {"type": "text"}},
    "parallel_tool_calls": True,
    "error": None,
    "incomplete_details": None,
  }

  yield _sse_event("response.created", {
    "type": "response.created",
    "sequence_number": seq,
    "response": skeleton,
  })
  seq += 1

  stream_error = None

  def _close_text_item():
    """Yield events to close an open text message item. Returns list of SSE strings."""
    nonlocal seq
    events = []

    # output_text.done
    events.append(_sse_event("response.output_text.done", {
      "type": "response.output_text.done",
      "item_id": msg_id,
      "output_index": output_index,
      "content_index": 0,
      "text": text_content,
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
        "text": text_content,
        "annotations": [],
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
          "text": text_content,
          "annotations": [],
        }],
      },
      "sequence_number": seq,
    }))
    seq += 1

    return events

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

        chunk_text = _get_chunk_content(chunk)
        chunk_tools = _get_chunk_tool_calls(chunk)
        chunk_usage = _get_chunk_usage(chunk)
        fr = dotty.get(chunk, "choices.0.finish_reason")

        if fr:
          finish_reason = fr

        input_tokens = chunk_usage.get("prompt_tokens", 0) or input_tokens
        output_tokens = chunk_usage.get("completion_tokens", 0) or output_tokens

        # --- Text content ---
        if chunk_text:
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

          text_content += chunk_text

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

        # --- Tool calls ---
        if chunk_tools:
          for tc in chunk_tools:
            tc_index = tc.get("index", 0)
            tool_state = tool_blocks.setdefault(
              tc_index,
              {"arguments": "", "emitted": False},
            )

            tc_id = tc.get("id")
            tc_name = dotty.get(tc, "function.name")
            tc_args = dotty.get(tc, "function.arguments", "")

            if tc_id:
              tool_state["id"] = tc_id
            if tc_name:
              tool_state["name"] = tc_name
            if tc_args:
              tool_state["arguments"] += tc_args

            if not tool_state.get("emitted") and tool_state.get("id"):
              # Close the text item first if open
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
              if tool_state.get("arguments"):
                yield _sse_event("response.function_call_arguments.delta", {
                  "type": "response.function_call_arguments.delta",
                  "item_id": call_id,
                  "output_index": output_index,
                  "delta": tool_state["arguments"],
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

  except Exception as e:
    logger.error(f"Error during responses stream conversion: {e}", exc_info=True)
    stream_error = str(e)

    # Emit error as text in a message item
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
      text_content = ""

    error_text = f"\n\n[Stream error: {stream_error}]"
    text_content += error_text
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

  # Close open text item
  if text_item_open:
    for evt in _close_text_item():
      yield evt

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
        if tool_state.get("arguments"):
          yield _sse_event("response.function_call_arguments.delta", {
            "type": "response.function_call_arguments.delta",
            "item_id": call_id,
            "output_index": output_index,
            "delta": tool_state["arguments"],
            "sequence_number": seq,
          })
          seq += 1
        tool_state["emitted"] = True

    if tool_state.get("emitted"):
      call_id = tool_state.get("id")
      tool_args = tool_state.get("arguments", "")

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

  # Final response.completed
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
    "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
  }

  yield _sse_event("response.completed", {
    "type": "response.completed",
    "sequence_number": seq,
    "response": final_response,
  })


# --- Route handler ---


@responses_compatible_routes.post("/v1/responses")
async def post_responses(request: Request, api_key: str = Depends(get_api_key)):
  try:
    body = await request.body()
    try:
      json_body = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
      return _responses_error(400, "Invalid JSON in request body")

    # Validate required fields
    if "model" not in json_body or not json_body["model"]:
      return _responses_error(400, "model is required")

    inp = json_body.get("input")
    if inp is None:
      return _responses_error(400, "input is required")

    request_model = json_body["model"]
    is_stream = json_body.get("stream", False)
    response_id = f"resp_{shortuuid.random()}"

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
      result = await proxy.chat_completion()
      response = _build_responses_response(result, request_model, response_id)
      return JSONResponse(content=response, status_code=200)

    completion = await proxy.serve()

    if completion is None:
      return _responses_error(500, "No completion returned")

    if is_stream:
      return StreamingResponse(
        _responses_stream_converter(completion, request_model, response_id),
        media_type="text/event-stream",
      )
    else:
      result = await proxy.consume_stream(completion)
      response = _build_responses_response(result, request_model, response_id)
      return JSONResponse(content=response, status_code=200)

  except HTTPException as e:
    return _responses_error(e.status_code, e.detail)
  except ValueError as e:
    return _responses_error(400, str(e))
  except Exception as e:
    logger.error(f"Unexpected error in responses handler: {e}", exc_info=True)
    return _responses_error(500, "Internal server error")
