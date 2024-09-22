from typing import Optional, AsyncGenerator
import httpx
import json

import modules.klmbr as klmbr
import modules.rcn as rcn
import modules.g1 as g1

import chat
import log

logger = log.setup_logger(__name__)

mods = {
  "klmbr": klmbr,
  "rcn": rcn,
  "g1": g1,
}


class LLM:
  url: str
  headers: dict

  model: str
  params: dict
  module: str

  def __init__(self, **kwargs):
    self.url = kwargs.get('url')
    self.headers = kwargs.get('headers', {})

    self.model = kwargs.get('model')
    self.params = kwargs.get('params', {})

    messages = kwargs.get('messages', [])
    self.messages = messages
    self.chat = chat.Chat.from_conversation(messages)

    self.module = kwargs.get('module')

  @property
  def chat_completion_endpoint(self):
    return f"{self.url}/chat/completions"

  def get_response_content(self, response):
    return response['choices'][0]['message']['content']

  def get_chunk_content(self, chunk):
    return chunk["choices"][0]["delta"]["content"]

  def parse_chunk(self, chunk):
    chunk_str = chunk.decode('utf-8').split("\n")[0]
    if chunk_str.startswith("data: "):
      chunk_str = chunk_str[6:]

    try:
      return json.loads(chunk_str)
    except json.JSONDecodeError:
      logger.error(f"Failed to parse chunk: {chunk_str}")
      return {}

  async def apply(self):
    logger.debug('Applying boost...')

    if self.module is None:
      logger.debug("No module specified")
      return self.stream_chat_completion()

    mod = mods.get(self.module)

    if mod is None:
      logger.error(f"Module '{self.module}' not found.")
      return

    logger.debug(f"Applying '{self.module}' to '{self.model}'")
    return await mod.apply(chat=self.chat, llm=self)

  async def stream_chat_completion(self, chat: Optional['chat.Chat'] = None):
    logger.debug(
      f"Streaming Chat Completion for '{self.chat_completion_endpoint}"
    )

    if chat is None:
      chat = self.chat

    async with httpx.AsyncClient(timeout=None) as client:
      async with client.stream(
        "POST",
        self.chat_completion_endpoint,
        headers=self.headers,
        json={
          "model": self.model,
          "messages": chat.history(),
          **self.params,
          "stream": True,
        }
      ) as response:
        async for chunk in response.aiter_bytes():
          yield chunk

  async def chat_completion(self, chat: Optional['chat.Chat'] = None):
    logger.debug(f"Chat Completion for '{self.chat_completion_endpoint}'")

    if chat is None:
      chat = self.chat

    async with httpx.AsyncClient(timeout=None) as client:
      body = {
        "model": self.model,
        "messages": chat.history(),
        **self.params, "stream": False
      }
      response = await client.post(
        self.chat_completion_endpoint, headers=self.headers, json=body
      )

      return response.json()

  async def consume_stream(self, stream: AsyncGenerator[bytes, None]):
    output_obj = None
    content = ""

    async for chunk_bytes in stream:
      chunk = self.parse_chunk(chunk_bytes)

      if output_obj is None:
        # First chunk - init
        output_obj = {
          "id": chunk["id"],
          "object": "chat.completion",
          "created": chunk["created"],
          "model": self.model,
          "system_fingerprint": chunk["system_fingerprint"],
          "choices":
            [
              {
                "index": choice["index"],
                "message":
                  {
                    "role": choice["delta"].get("role", "assistant"),
                    "content": ""
                  },
                "finish_reason": None
              } for choice in chunk["choices"]
            ],
          "usage":
            {
              "prompt_tokens": 0,
              "completion_tokens": 0,
              "total_tokens": 0
            }
        }

      chunk_content = self.get_chunk_content(chunk)
      content += chunk_content

    # Set the aggregated content
    if output_obj:
      output_obj["choices"][0]["message"]["content"] = content

    return output_obj
