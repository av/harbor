from typing import Optional, AsyncGenerator
import traceback

import json
import asyncio
import time
import httpx
import uuid

from config import INTERMEDIATE_OUTPUT, EXTRA_LLM_PARAMS
from llm_registry import llm_registry
import chat as ch
import log
import format
import mods
import tools
import tools.registry

logger = log.setup_logger(__name__)

BOOST_PARAM_PREFIX = "@boost_"


class LLM:
  url: str
  headers: dict
  query_params: dict

  model: str
  params: dict
  boost_params: dict
  module: str

  queue: asyncio.Queue
  is_streaming: bool
  is_final_stream: bool

  cpl_id: int

  def __init__(self, **kwargs):
    self.id = str(uuid.uuid4())
    self.url = kwargs.get('url')
    self.headers = kwargs.get('headers', {})
    self.query_params = kwargs.get('query_params', {})

    self.model = kwargs.get('model')
    self.split_params(kwargs.get('params', {}))

    self.chat = self.resolve_chat(**kwargs)
    self.messages = self.chat.history()

    self.module = kwargs.get('module')

    self.queue = asyncio.Queue()
    self.queues = []
    self.is_streaming = False
    self.is_final_stream = False

    self.cpl_id = 0

  @property
  def chat_completion_endpoint(self):
    return f"{self.url}/chat/completions"

  def split_params(self, params: dict):
    self.params = {
      k: v for k, v in {
        **EXTRA_LLM_PARAMS.value,
        **params
      }.items() if not k.startswith(BOOST_PARAM_PREFIX)
    }
    self.boost_params = {
      k[len(BOOST_PARAM_PREFIX):]: v
      for k, v in params.items()
      if k.startswith(BOOST_PARAM_PREFIX)
    }

  def generate_system_fingerprint(self):
    return "fp_boost"

  def generate_chunk_id(self):
    self.cpl_id += 1
    return f"chatcmpl-{self.cpl_id}"

  def get_response_content(self, params: dict, response: dict):
    content = response['choices'][0]['message']['content']

    if 'response_format' in params and 'type' in params['response_format']:
      if params['response_format']['type'] == 'json_schema' or params[
        'response_format']['type'] == 'json':
        return json.loads(content)

    return content

  def get_chunk_content(self, chunk):
    try:
      choices = chunk.get("choices", [])
      choice = choices[0] if choices and len(choices) > 0 else {}
      delta = choice.get("delta", {})
      return delta.get("content", "")
    except (KeyError, IndexError):
      logger.error(f"Unexpected chunk format: {chunk}")
      return ""

  def get_chunk_tool_calls(self, chunk):
    try:
      choices = chunk.get("choices", [])
      choice = choices[0] if choices and len(choices) > 0 else {}
      delta = choice.get("delta", {})
      return delta.get("tool_calls", [])
    except (KeyError, IndexError):
      logger.error(f"Unexpected chunk format: {chunk}")
      return

  def parse_chunk(self, chunk):
    if isinstance(chunk, dict):
      return chunk

    if isinstance(chunk, bytes):
      chunk = chunk.decode('utf-8')

    chunk_str = chunk.split("\n")[0]
    if chunk_str.startswith("data: "):
      chunk_str = chunk_str[6:]

    return json.loads(chunk_str)

  def output_from_chunk(self, chunk):
    return {
      "id": chunk["id"],
      "object": "chat.completion",
      "created": chunk["created"],
      "model": self.model,
      "system_fingerprint": self.generate_system_fingerprint(),
      "choices":
        [
          {
            "index": choice["index"],
            "message":
              {
                "role": choice["delta"].get("role", "assistant"),
                "content": choice["delta"].get("content", "")
              },
            "finish_reason": None
          } for choice in chunk["choices"]
        ],
      "usage": {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0
      }
    }

  def chunk_from_delta(self, delta: dict):
    now = int(time.time())

    return {
      "id": self.generate_chunk_id(),
      "object": "chat.completion.chunk",
      "created": now,
      "model": self.model,
      "system_fingerprint": self.generate_system_fingerprint(),
      "choices": [{
        "index": 0,
        "delta": delta,
        "finish_reason": None
      }]
    }

  def chunk_from_message(self, message: str):
    return self.chunk_from_delta({"role": "assistant", "content": message})

  def chunk_from_tool_call(self, tool_call: dict):
    return self.chunk_from_delta(
      {
        "role": "assistant",
        "tool_calls": [tool_call]
      }
    )

  def chunk_to_string(self, chunk):
    if isinstance(chunk, dict):
      chunk = f"data: {json.dumps(chunk)}\n\n"

    return chunk

  def is_tool_call(self, chunk):
    choices = chunk.get("choices", [])
    choice = choices[0] if choices and len(choices) > 0 else {}
    delta = choice.get("delta", {})
    has_tool_calls = delta.get("tool_calls", [])
    return len(has_tool_calls) > 0

  def event_to_string(self, event, data):
    payload = {'object': 'boost.listener.event', 'event': event, 'data': data}

    return f"data: {json.dumps(payload)}\n\n"

  async def serve(self):
    logger.debug('Serving boosted LLM...')
    llm_registry.register(self)

    async def apply_mod():
      if self.module is None:
        logger.debug("No module specified")
        await self.stream_final_completion()
        await self.emit_done()
        return

      mod = mods.registry.get(self.module)

      if mod is None:
        logger.error(f"Module '{self.module}' not found.")
        return

      logger.debug(f"Applying '{self.module}' to '{self.model}'")
      try:
        self.chat.llm = self
        await mod.apply(chat=self.chat, llm=self)
      except Exception as e:
        logger.error(f"Failed to apply module '{self.module}': {e}")
        for line in traceback.format_tb(e.__traceback__):
          logger.error(line)

      logger.debug(f"'{self.module}' application complete for '{self.model}'")
      await self.emit_done()

    asyncio.create_task(apply_mod())
    return self.response_stream()

  async def generator(self):
    self.is_streaming = True

    while self.is_streaming:
      chunk = await self.queue.get()

      if chunk is None:
        break
      yield chunk

  async def response_stream(self):
    async for chunk in self.generator():
      # Final stream is always passed back as
      # that's the useful payload of a given iteration
      if INTERMEDIATE_OUTPUT.value or self.is_final_stream:
        yield chunk

  async def listen(self):
    queue = asyncio.Queue()
    self.queues.append(queue)

    while True:
      chunk = await queue.get()
      if chunk is None:
        break
      yield chunk

  async def emit_status(self, status):
    await self.emit_message(format.format_status(status))

  async def emit_artifact(self, artifact):
    await self.emit_message(format.format_artifact(artifact))

  async def emit_message(self, message):
    await self.emit_chunk(self.chunk_from_message(message))

  async def emit_chunk(self, chunk):
    await self.emit_data(self.chunk_to_string(chunk))

  async def emit_data(self, data):
    await self.queue.put(data)
    await self.emit_to_listeners(data)

  async def emit_to_listeners(self, data):
    for queue in self.queues:
      await queue.put(data)

  async def emit_listener_event(self, event, data):
    await self.emit_to_listeners(self.event_to_string(event, data))

  async def emit_done(self):
    await self.emit_data('data: [DONE]')
    await self.emit_data(None)
    self.is_streaming = False

  async def stream_final_completion(self, **kwargs):
    self.is_final_stream = True
    return await self.stream_chat_completion(**kwargs)

  async def stream_chat_completion(self, **kwargs):
    request = await self.resolve_request(**kwargs)

    chat = request.get("chat", self.chat)
    params = request.get("params", self.params)
    model = request.get("model", self.model)
    url = request.get("url", self.url)
    headers = request.get("headers", self.headers)
    query_params = request.get("query_params", self.query_params)

    logger.debug(f"Params: {params}")
    logger.debug(f"Chat: {str(chat):.256}")

    result = ""
    pending_tool_calls = {}    # Track tool calls being built
    first_tool_call_id = None

    async with httpx.AsyncClient(timeout=None) as client:
      while True:    # Loop to handle tool calls and continuations
        body = {
          "model": model,
          "messages": chat.history(),
          **params, "stream": True,
          "stream_options": {
            "include_usage": True,
          }
        }

        logger.info(body)

        # Flag to determine if we need to execute tool calls
        end_of_stream = False
        current_stream_content = ""

        async with client.stream(
          "POST",
          f"{url}/chat/completions",
          headers=headers,
          params=query_params,
          json=body
        ) as response:
          response.raise_for_status()
          buffer = b''

          async for chunk in response.aiter_bytes():
            buffer += chunk
            # await self.emit_chunk(chunk)

            while b'\n' in buffer:
              line, buffer = buffer.split(b'\n', 1)
              line = line.decode('utf-8').strip()

              if not line or line.startswith(':'):
                continue

              if line == 'data: [DONE]':
                end_of_stream = True
                continue

              if not line.startswith('data:'):
                continue

              try:
                parsed = self.parse_chunk(line)

                # Safely check finish_reason
                choices = parsed.get("choices", [])
                if choices and len(choices) > 0:
                  finish_reason = choices[0].get("finish_reason")
                  if finish_reason == "tool_calls":
                    end_of_stream = True

                # Extract content for regular text responses
                content = self.get_chunk_content(parsed)
                if content:
                  current_stream_content += content
                  result += content

                # Process tool call chunks
                if self.is_tool_call(parsed):
                  # Extract tool call data safely
                  choices = parsed.get("choices", [])
                  if not choices:
                    continue

                  delta = choices[0].get("delta", {})
                  tool_calls_data = delta.get("tool_calls", [])

                  if not tool_calls_data:
                    continue

                  tool_call = tool_calls_data[0]
                  index = tool_call.get("index", 0)

                  # Store the first tool call ID we see
                  if tool_call.get("id") and not first_tool_call_id:
                    first_tool_call_id = tool_call.get("id")

                  # Initialize tool call if new
                  if index not in pending_tool_calls:
                    pending_tool_calls[index] = {
                      "id": tool_call.get("id") or
                            first_tool_call_id,    # Use stored ID as fallback
                      "function":
                        {
                          "name": tool_call.get("function", {}).get("name"),
                          "arguments": ""
                        },
                      "type": tool_call.get("type") or "function"
                    }

                  # Update arguments
                  function_args = tool_call.get("function", {}).get("arguments")
                  if index in pending_tool_calls and function_args is not None:
                    pending_tool_calls[index]["function"]["arguments"
                                                         ] += function_args

                  logger.debug(f"Tool call chunk: {parsed}")
                else:
                  await self.emit_chunk(parsed)

              except json.JSONDecodeError:
                logger.error(f"Failed to parse chunk: \"{line}\"")
              except Exception as e:
                logger.error(f"Error processing chunk: {str(e)}")
                for line in traceback.format_tb(e.__traceback__):
                  logger.error(line)

        # After stream ends, check if we need to execute tool calls
        if pending_tool_calls and (end_of_stream or not current_stream_content):
          for index, tool_call in pending_tool_calls.items():
            try:
              logger.warning(f"Executing tool call: {tool_call}")
              name = tool_call["function"]["name"]

              if not tools.registry.is_local_tool(name):
                # Passing control back to boost client
                await self.emit_chunk(self.chunk_from_tool_call(tool_call))
                return result

              if not name:
                continue    # Skip tool calls with no name

              # Parse arguments
              args_str = tool_call["function"]["arguments"]
              try:
                args = json.loads(args_str) if args_str.strip() else {}
              except json.JSONDecodeError:
                logger.error(f"Invalid JSON in tool call arguments: {args_str}")
                args = {"query": args_str}    # Fallback for malformed JSON

              chat.tool_call(tool_call)
              tool_result = await tools.registry.call_tool(name, **args)
              chat.tool(tool_call["id"], tool_result)

              logger.info(f"Called name={name}, args={args}")
            except Exception as e:
              logger.error(f"Error executing tool call: {e}")
              chat.tool(tool_call["id"], f"Error: {str(e)}")

          # Reset pending tool calls
          pending_tool_calls = {}
          first_tool_call_id = None

          # Continue with the updated chat (loop back to beginning)
          continue

        # If no tool calls or content was streamed, we're done
        break

    return result

  async def chat_completion(self, **kwargs):
    chat = self.resolve_chat(**kwargs)
    params = await self.resolve_request_params(**kwargs)
    should_resolve = kwargs.get("resolve", False)

    logger.debug(f"Chat Completion for '{self.chat_completion_endpoint}'")
    logger.debug(f"Params: {params}")
    logger.debug(f"Chat: {str(chat):.256}...")
    if chat is None:
      chat = self.chat

    async with httpx.AsyncClient(timeout=None) as client:
      body = {
        "model": self.model,
        "messages": chat.history(),
        **params, "stream": False
      }
      response = await client.post(
        self.chat_completion_endpoint, headers=self.headers, json=body
      )
      result = response.json()
      if should_resolve:
        return self.get_response_content(params, result)
      return result

  async def consume_stream(self, stream: AsyncGenerator[bytes, None]):
    output_obj = None
    content = ""
    tool_calls = []

    async for chunk_bytes in stream:
      chunk = self.parse_chunk(chunk_bytes)
      if output_obj is None:
        output_obj = self.output_from_chunk(chunk)
      chunk_content = self.get_chunk_content(chunk)
      chunk_tools = self.get_chunk_tool_calls(chunk)

      content += chunk_content
      tool_calls.extend(chunk_tools)

    if output_obj:
      output_obj["choices"][0]["message"]["content"] = content

      if len(tool_calls) > 0:
        output_obj["choices"][0]["message"]["tool_calls"] = tool_calls
        output_obj["choices"][0]["finish_reason"] = "tool_calls"

    return output_obj

  async def resolve_request_params(self, **kwargs):
    params = {
      "model": kwargs.get("model", self.model),
      **self.params,
      **kwargs.get("params", {}),
    }

    if kwargs.get("schema"):
      params['response_format'] = {
        'type': 'json_schema',
        'json_schema':
          {
            'name': 'StructuredResponseSchema',
            'schema': kwargs['schema'].model_json_schema()
          }
      }

    return params

  def resolve_chat(
    self,
    messages: Optional[list] = None,
    chat: Optional['ch.Chat'] = None,
    prompt: Optional[str] = None,
    **prompt_kwargs
  ):
    if chat is not None:
      return chat

    if messages is not None:
      return ch.Chat.from_conversation(messages)

    if prompt is not None:
      message = prompt.format(**prompt_kwargs)
      return ch.Chat.from_conversation([{"role": "user", "content": message}])

    return self.chat

  async def resolve_model(self, model: Optional[str] = None, **rest) -> str:
    return model or self.model

  async def resolve_headers(self, **kwargs):
    return self.headers

  async def resolve_query_params(self, **kwargs):
    return self.query_params

  async def resolve_url(self, **kwargs):
    return self.url

  async def resolve_request(self, **kwargs):
    logger.debug('resolving')

    tasks = {
      "url": self.resolve_url(**kwargs),
      "headers": self.resolve_headers(**kwargs),
      "params": self.resolve_request_params(**kwargs),
      "model": self.resolve_model(**kwargs),
      "query_params": self.resolve_query_params(**kwargs),
    }

    values = await asyncio.gather(*tasks.values())
    results = {k: v for k, v in zip(tasks.keys(), values)}
    results["chat"] = self.resolve_chat(**kwargs)

    return results
