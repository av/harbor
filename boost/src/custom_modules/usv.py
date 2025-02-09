from pydantic import BaseModel, Field

import asyncio
import chat as ch
import log
import llm
import selection

# USV - Unique Selection and Validation
ID_PREFIX = 'usv'
logger = log.setup_logger(ID_PREFIX)

continue_params = {
  "max_tokens": 2,
  "temperature": 0.8,
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

attempts = 5

class Choice(BaseModel):
  choice: int = Field(
    description = "Index of the chosen option",
    ge=1,
    le=attempts
  )

async def continue_generation(**kwargs):
  chat = kwargs['chat']
  llm = kwargs['llm']

  options = []
  for i in range(attempts):
    side_chat = chat.clone()
    if len(options) > 0:
      newline = "\n"
      side_chat.system(f"""
Your response should be unique and not include any of the following options:
{newline.join(f"{i+1}. '{option}'" for i, option in enumerate(options))}
      """)

    option = await llm.chat_completion(
        chat=side_chat, params=continue_params, resolve=True
    )
    options.append(option)

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