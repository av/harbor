"""
title: artifact
author: av
author_url: https://github.com/av
description: seeding artifact programmatically
version: 0.0.1
"""

from functools import wraps
import time
import logging
import asyncio
import json
import re

from typing import (
  List,
  Optional,
  AsyncGenerator,
  Callable,
  Awaitable,
  Generator,
  Iterator,
)
from open_webui.constants import TASKS
from open_webui.apps.ollama import main as ollama

# ==============================================================================

name = "artf"
max_steps = 10
final_answer = "<final_answer>"

detect_final = [
  "final answer",
  "final answer.",
  "final answer:",
  "FINAL ANSWER",
]

base_prompt = """
You are an expert AI assistant that explains your reasoning step by step.
For each step, write at most two sentences. BE CONCISE, CLEAR, AND SPECIFIC.
YOU WILL BE PENALIZED FOR WRITING TOO MUCH.
Decide if you need another step or if you're ready to give the final answer.
Avoid markdown in your reply, use HTML tags.
In your response write "ACTION" followed by either 'continue' or '{final_answer}'.
USE AS MANY REASONING STEPS AS POSSIBLE. AT LEAST 3.
BE AWARE OF YOUR LIMITATIONS AS AN LLM AND WHAT YOU CAN AND CANNOT DO.
IN YOUR REASONING, INCLUDE EXPLORATION OF ALTERNATIVE ANSWERS.
CONSIDER YOU MAY BE WRONG, AND IF YOU ARE WRONG IN YOUR REASONING, WHERE IT WOULD BE.
FULLY TEST ALL OTHER POSSIBILITIES. YOU CAN BE WRONG.
WHEN YOU SAY YOU ARE RE-EXAMINING, ACTUALLY RE-EXAMINE, AND USE ANOTHER APPROACH TO DO SO.
DO NOT JUST SAY YOU ARE RE-EXAMINING. USE AT LEAST 3 METHODS TO DERIVE THE ANSWER. USE BEST PRACTICES.
""".strip().format(final_answer=final_answer, max_steps=max_steps)

# ==============================================================================

def throttle(wait_ms):
    def decorator(func):
        last_call = 0
        task = None

        @wraps(func)
        async def wrapper(*args, **kwargs):
            nonlocal last_call, task
            now = time.time()

            if now - last_call >= wait_ms / 1000:
                last_call = now
                if task:
                    task.cancel()
                task = asyncio.create_task(func(*args, **kwargs))
                return await task
            elif task:
                return await task
            else:
                return None

        return wrapper
    return decorator

def is_final_answer(message: str) -> bool:
  return final_answer in message or any([word in message.lower() for word in detect_final])

def setup_logger():
  logger = logging.getLogger(__name__)
  if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.set_name(name)
    formatter = logging.Formatter(
      "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
  return logger


logger = setup_logger()


class Content:
  data: dict

  def __init__(self):
    self.data = {}

  def set(self, key: str, value: str):
    self.data[key] = value
    return self

  def add(self, key: str, value: str):
    if key in self.data:
      self.data[key] += value
    else:
      self.data[key] = value

    return self

  def add_word(self, key: str, value: str):
    self.add(key, f" {value}")
    return self

  def add_tag(self, key: str, tag: str, value: str):
    self.add(key, f"<{tag}>{value}</{tag}>")
    return self

  def add_hr(self, key: str):
    self.add(key, "<hr />")
    return self

  def render(self):
    return f"""
{self.render_artifact()}

---

{self.render_message()}
""".strip()

  def render_message(self):
    return f"""
{self.data.get("message_content", "")}
""".strip()

  # Make a one-liner artifact
  def render_html(self, html: str):
    pattern = r'\s+|(?<=\>)\s+(?=\<)'
    replacement = ' '
    cleaned_html = re.sub(pattern, replacement, html)
    return f"""
```html
{cleaned_html}
```
"""

  def render_artifact(self):
    content = self.data.get("artifact_content", "")
    html = f"""
<html lang="en">
  <head>
    <title>🔮</title>
    <style>
      body {{
        font-family: ui-sans-serif,system-ui,sans-serif,"Apple Color Emoji","Segoe UI Emoji",Segoe UI Symbol,"Noto Color Emoji";
        background-color: transparent;
        color: #ececec;
        padding: 1rem;
      }}
    </style>
  </head>
  <body>
    <h1>🔮</h1>
    {content}

    <div id="bottom"></div>
    <script>
      const bottom = document.getElementById("bottom");
      bottom.scrollIntoView();
    </script>
  </body>
</html>
    """

    return self.render_html(html)


# ==============================================================================

EventEmitter = Callable[[dict], Awaitable[None]]


class Pipe:
  __current_event_emitter__: EventEmitter
  __question__: str
  __model__: str

  def __init__(self):
    self.type = "manifold"

  def pipes(self) -> list[dict[str, str]]:
    ollama.get_all_models()
    models = ollama.app.state.MODELS

    out = [
      {
        "id": f"{name}-{key}",
        "name": f"{name} {models[key]['name']}"
      } for key in models
    ]
    logger.debug(f"Available models: {out}")

    return out

  def resolve_model(self, body: dict) -> str:
    model_id = body.get("model")
    without_pipe = ".".join(model_id.split(".")[1:])
    return without_pipe.replace(f"{name}-", "")

  def resolve_question(self, body: dict) -> str:
    return body.get("messages")[-1].get("content").strip()

  async def pipe(
    self,
    body: dict,
    __user__: dict,
    __event_emitter__=None,
    __task__=None,
    __model__=None,
  ) -> str | Generator | Iterator:
    model = self.resolve_model(body)
    base_question = self.resolve_question(body)

    if __task__ == TASKS.TITLE_GENERATION:
      content = await self.get_completion(model, body.get("messages"))
      return f"{name}: {content}"

    logger.debug(f"Pipe {name} received: {body}")

    # TODO: concurrency
    self.__model__ = model
    self.__question__ = base_question
    self.__current_event_emitter__ = __event_emitter__

    content = Content()
    content.add_tag("artifact_content", "h3",
                    base_question).add_hr("artifact_content")
    content.set("message_content", '...')

    await self.emit_status("info", "Thinking...", False)

    messages = [
      {
        "role": "system",
        "content": base_prompt
      }, {
        "role": "user",
        "content": base_question
      }, {
        "role":
          "assistant",
        "content":
          "Thank you! I will now think step by step following my instructions, starting at the beginning after decomposing the problem."
      }, {
        "role": "user",
        "content": "Provide the first step."
      }
    ]

    steps = 0
    last_message = ""

    while True:
      if last_message == "":
        content.add_tag("artifact_content", "h3", f"Step: {steps + 1}")

      async for chunk in self.get_streaming_completion(messages):
        last_message += chunk
        content.add("artifact_content", chunk)
        await self.emit_replace(content.render())

      # Smaller models can end generating content early
      # if last_message.strip() != "":
      steps += 1
      messages.append({"role": "assistant", "content": f"\n{last_message}\n"})

      if is_final_answer(last_message) or steps >= max_steps:
        break
      else:
        messages.append({"role": "user", "content": f"Provide the next step. You have {max_steps - steps} remaining."})

      last_message = ""

    content.set("message_content", "\n\n")

    logger.debug(f"Final step: messages={len(messages)}, chat={content.render_message()}")

    messages.append({
      "role": "user",
      "content": f"Now, provide the final answer based on your reasoning above. You don't have to mention {final_answer} in your response anymore."
    })

    await self.emit_replace(content.render())
    await self.emit_status("info", "Final answer.", False)

    async for chunk in self.get_streaming_completion(messages):
      await self.emit_message(chunk)

    await self.done()

  async def progress(
    self,
    message: str,
  ):
    logger.debug(f"Progress: {message}")
    await self.emit_status("info", message, False)

  async def done(self,):
    await self.emit_status("info", "Fin.", True)

  async def emit_message(self, message: str):
    await self.__current_event_emitter__(
      {
        "type": "message",
        "data": {
          "content": message
        }
      }
    )

  @throttle(125)
  async def emit_replace(self, message: str):
    await self.__current_event_emitter__(
      {
        "type": "replace",
        "data": {
          "content": message
        }
      }
    )

  async def emit_status(self, level: str, message: str, done: bool):
    await self.__current_event_emitter__(
      {
        "type": "status",
        "data":
          {
            "status": "complete" if done else "in_progress",
            "level": level,
            "description": message,
            "done": done,
          },
      }
    )

  async def get_streaming_completion(
    self,
    messages,
  ) -> AsyncGenerator[str, None]:
    response = await ollama.generate_openai_chat_completion(
      {
        "model": self.__model__,
        "messages": messages,
        "stream": True
      }
    )

    async for chunk in response.body_iterator:
      for part in self.get_chunk_content(chunk):
        yield part

  async def get_message_completion(self, model: str, content):
    async for chunk in self.get_streaming_completion(
      [{
        "role": "user",
        "content": content
      }]
    ):
      yield chunk

  async def get_completion(self, model: str, messages):
    response = await ollama.generate_openai_chat_completion(
      {
        "model": model,
        "messages": messages,
        "stream": False
      }
    )

    return self.get_response_content(response)

  async def stream_prompt_completion(self, prompt, **format_args):
    complete = ""
    async for chunk in self.get_message_completion(
      self.__model__,
      prompt.format(**format_args),
    ):
      complete += chunk
      await self.emit_message(chunk)
    return complete

  def get_response_content(self, response):
    try:
      return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
      logger.error(
        f"ResponseError: unable to extract content from \"{response[:100]}\""
      )
      return ""

  def get_chunk_content(self, chunk):
    chunk_str = chunk.decode("utf-8")
    if chunk_str.startswith("data: "):
      chunk_str = chunk_str[6:]

    chunk_str = chunk_str.strip()

    if chunk_str == "[DONE]" or not chunk_str:
      return

    try:
      chunk_data = json.loads(chunk_str)
      if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
        delta = chunk_data["choices"][0].get("delta", {})
        if "content" in delta:
          yield delta["content"]
    except json.JSONDecodeError:
      logger.error(f"ChunkDecodeError: unable to parse \"{chunk_str[:100]}\"")
