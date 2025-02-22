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

logger = log.setup_logger(__name__)

BOOST_PARAM_PREFIX="@boost_"

class LLM:
  url: str
  headers: dict

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
      k: v for k, v in {**EXTRA_LLM_PARAMS.value, **params}.items() if not k.startswith(BOOST_PARAM_PREFIX)
    }
    self.boost_params = {
      k[len(BOOST_PARAM_PREFIX):]: v for k, v in params.items() if k.startswith(BOOST_PARAM_PREFIX)
    }

  def generate_system_fingerprint(self):
    return "fp_boost"

  def generate_chunk_id(self):
    self.cpl_id += 1
    return f"chatcmpl-{self.cpl_id}"

  def get_response_content(self, params: dict, response: dict):
    content = response['choices'][0]['message']['content']

    if 'response_format' in params and 'type' in params['response_format']:
      if params['response_format']['type'] == 'json_schema' or params['response_format']['type'] == 'json':
        return json.loads(content)

    return content

  def get_chunk_content(self, chunk):
    return chunk["choices"][0]["delta"]["content"]

  def parse_chunk(self, chunk):
    if isinstance(chunk, dict):
      return chunk

    if isinstance(chunk, bytes):
      chunk = chunk.decode('utf-8')

    chunk_str = chunk.split("\n")[0]
    if chunk_str.startswith("data: "):
      chunk_str = chunk_str[6:]

    try:
      return json.loads(chunk_str)
    except json.JSONDecodeError:
      logger.error(f"Failed to parse chunk: {chunk_str}")
      return {}

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

  def chunk_from_message(self, message: str):
    now = int(time.time())

    return {
      "id":
        self.generate_chunk_id(),
      "object":
        "chat.completion.chunk",
      "created":
        now,
      "model":
        self.model,
      "system_fingerprint":
        self.generate_system_fingerprint(),
      "choices":
        [
          {
            "index": 0,
            "delta": {
              "role": "assistant",
              "content": message
            },
            "finish_reason": None
          }
        ]
    }

  def chunk_to_string(self, chunk):
    if isinstance(chunk, dict):
      chunk = f"data: {json.dumps(chunk)}\n\n"

    return chunk

  def event_to_string(self, event, data):
    payload = {
      'object': 'boost.listener.event',
      'event': event,
      'data': data
    }

    return f"data: {json.dumps(payload)}\n\n"

  async def serve(self):
    logger.debug('Serving boosted LLM...')
    llm_registry.register(self)

    if self.module is None:
      logger.debug("No module specified")
      return self.stream_chat_completion()

    mod = mods.registry.get(self.module)

    if mod is None:
      logger.error(f"Module '{self.module}' not found.")
      return

    async def apply_mod():
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
    await self.emit_data(None)
    self.is_streaming = False

  async def stream_final_completion(self, **kwargs):
    self.is_final_stream = True
    return await self.stream_chat_completion(**kwargs)

  async def resolve_request_params(self, **kwargs):
    params = {
      "model": kwargs.get("model", self.model),
      **self.params,
      **kwargs.get("params", {}),
    }

    if kwargs.get("schema"):
      params['response_format'] = {
        'type': 'json_schema',
        'json_schema': {
          'name': 'StructuredResponseSchema',
          'schema': kwargs['schema'].model_json_schema()
        }
      }

    return params

  async def stream_chat_completion(self, **kwargs):
    chat = self.resolve_chat(**kwargs)
    params = await self.resolve_request_params(**kwargs)

    logger.debug(
      f"Streaming Chat Completion for '{self.chat_completion_endpoint}"
    )
    logger.debug(f"Params: {params}")
    logger.debug(f"Chat: {str(chat):.256}")

    if chat is None:
      chat = self.chat

    result = ""

    async with httpx.AsyncClient(timeout=None) as client:
      async with client.stream(
        "POST",
        self.chat_completion_endpoint,
        headers=self.headers,
        json={
          "model": self.model,
          "messages": chat.history(),
          **params,
          "stream": True,
        }
      ) as response:
        async for chunk in response.aiter_bytes():
          parsed = self.parse_chunk(chunk)
          content = self.get_chunk_content(parsed)
          result += content

          # We emit done after the module
          # application has completed
          if not '[DONE]' in f"{chunk}":
            await self.emit_chunk(chunk)

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

    async for chunk_bytes in stream:
      chunk = self.parse_chunk(chunk_bytes)
      if output_obj is None:
        output_obj = self.output_from_chunk(chunk)
      chunk_content = self.get_chunk_content(chunk)
      content += chunk_content

    if output_obj:
      output_obj["choices"][0]["message"]["content"] = content

    return output_obj

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
