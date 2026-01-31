from typing import Optional, AsyncGenerator
import traceback

import json
import asyncio
import time
import httpx

from config import (
  INTERMEDIATE_OUTPUT,
  HARBOR_AGENT_LLM_URL,
  HARBOR_AGENT_LLM_PARAMS,
  HARBOR_AGENT_LLM_EXTRA_HEADERS,
  HARBOR_AGENT_LLM_EXTRA_QUERY_PARAMS
)
import chat as ch
import log
import format

logger = log.setup_logger(__name__)

HARBOR_PARAM_PREFIX = "@harbor_"

class LLM:
  @staticmethod
  def from_config(
    **kwargs
  ):
    url = HARBOR_AGENT_LLM_URL.value
    params = HARBOR_AGENT_LLM_PARAMS.value
    headers = HARBOR_AGENT_LLM_EXTRA_HEADERS.value
    qs = HARBOR_AGENT_LLM_EXTRA_QUERY_PARAMS.value

    return LLM(
      url=url,
      headers=headers,
      model=params.get('model'),
      params=params,
      qs=qs,
      messages=kwargs.get('messages', []),
    )

  url: str
  headers: dict
  qs: dict

  model: str
  params: dict
  harbor_params: dict

  queue: asyncio.Queue
  is_streaming: bool
  is_final_stream: bool

  cpl_id: int

  def __init__(self, **kwargs):
    self.url = kwargs.get('url')
    self.headers = kwargs.get('headers', {})
    self.qs = kwargs.get('qs', {})

    self.split_params(kwargs.get('params', {}))
    self.model = self.params.get('model', kwargs.get('model'))

    self.chat = self.resolve_chat(**kwargs)
    self.messages = self.chat.history()

    self.queue = asyncio.Queue()
    self.is_streaming = False
    self.is_final_stream = False

    self.cpl_id = 0

  @property
  def chat_completion_endpoint(self):
    return f"{self.url}/chat/completions"

  def split_params(self, params: dict):
    self.params = {
      k: v for k, v in params.items() if not k.startswith(HARBOR_PARAM_PREFIX)
    }
    self.harbor_params = {
      k[len(HARBOR_PARAM_PREFIX):]: v
      for k, v in params.items()
      if k.startswith(HARBOR_PARAM_PREFIX)
    }

  def generate_system_fingerprint(self):
    return "fp_agent"

  def generate_chunk_id(self):
    return f"chatcmpl-{++self.cpl_id}"

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

  async def emit_status(self, status):
    await self.emit_message(format.format_status(status))

  async def emit_message(self, message):
    await self.emit_chunk(self.chunk_from_message(message))

  async def emit_chunk(self, chunk):
    await self.queue.put(self.chunk_to_string(chunk))

  async def emit_done(self):
    await self.queue.put(None)
    self.is_streaming = False

  async def stream_final_completion(self, **kwargs):
    self.is_final_stream = True
    return await self.stream_chat_completion(**kwargs)

  async def resolve_request_params(self, **kwargs):
    params = {
      "model": kwargs.get("model", self.model),
      **self.params,
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
      f"Streaming Chat Completion for '{self.chat_completion_endpoint}', '{params}'"
    )

    if chat is None:
      chat = self.chat

    result = ""

    async with httpx.AsyncClient(timeout=None) as client:
      async with client.stream(
        "POST",
        self.chat_completion_endpoint,
        headers=self.headers,
        params=self.qs,
        json={
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
    logger.debug(f"Chat: {chat}")
    if chat is None:
      chat = self.chat

    async with httpx.AsyncClient(timeout=None) as client:
      body = {
        "messages": chat.history(),
        **params,
        "stream": False
      }
      logger.debug(f"Endpoint: {self.chat_completion_endpoint}")
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
