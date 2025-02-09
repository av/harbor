from pydantic import BaseModel, Field

import asyncio
import chat as ch
import log
import llm
import selection

# TMSV - Temperature-Driven Selection and Validation
ID_PREFIX = 'tmsv'
logger = log.setup_logger(ID_PREFIX)

continue_params = {
  "max_tokens": 1,
}

selection_prompt = """
Below is an unfinished conversation between the User and their assistant.
Choose how the conversation should continue.

You will reply with a JSON object in a format like this:
{{ "choice": 0 }}, where the number is the index of the chosen option.

Conversation:
{conversation}

Options:
{options}
""".strip()

param_variations = [
  {
    "temperature": 0.1,
  },
  {
    "temperature": 0.25,
  },
  {
    "temperature": 0.5,
  },
  {
    "temperature": 0.7,
  },
  {
    "temperature": 1.0,
  },
]

class Choice(BaseModel):
  choice: int = Field(
    description = "The index of the chosen option",
    ge=1,
    le=len(param_variations)
  )

async def continue_generation(**kwargs):
  chat = kwargs['chat']
  llm = kwargs['llm']

  tasks = []
  for params in param_variations:
      side_chat = chat.clone()
      final_params = {
        **continue_params,
        **params,
      }
      task = llm.chat_completion(
          chat=side_chat, params=final_params, resolve=True
      )
      tasks.append(task)

  options = await asyncio.gather(*tasks)
  rendered_options = "\n\n\n".join([f"{i}. {option}" for i, option in enumerate(options, 1)])

  result = await llm.chat_completion(
    prompt=selection_prompt,
    schema=Choice,
    conversation=chat,
    options=rendered_options,
    resolve=True,
  )

  logger.debug(f"Opts: {options}, Choice: {result['choice']}")

  next_token = options[result['choice'] - 1]
  return next_token, rendered_options

async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  generated = 0
  guidance_chat = chat.clone()
  guidance_chat.assistant("")
  assistant_message = guidance_chat.tail

  # while generated < 512:
  while True:
    next_token, options = await continue_generation(chat=guidance_chat, llm=llm)
    if next_token == '':
      break
    assistant_message.content += next_token + ''
    # await llm.emit_message(f'\n{options}\n### {next_token}\n')
    await llm.emit_message(next_token)
    generated += 1