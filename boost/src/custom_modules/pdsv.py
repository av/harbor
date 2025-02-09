from pydantic import BaseModel, Field

import asyncio
import chat as ch
import log
import llm
import selection

# PDSV - Personality-Driven Selection and Validation
ID_PREFIX = 'pdsv'
logger = log.setup_logger(ID_PREFIX)

continue_params = {
  "max_tokens": 4,
  "temperature": 0,
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

system_prompts = {
    "overfit": """
You challenge common assumptions. For each problem:
- Consider if you're jumping to familiar but wrong answers
- Look for cases where obvious answers fail
- Test multiple interpretations
- Question if you're forcing a known solution to fit
- Start fresh if you catch yourself following a memorized path
""",

    "tracker": """
You ensure complete solutions. For each puzzle:
- Track each requirement as a separate test case
- Mark requirements as pass/fail for each proposed solution
- Reject partial matches that don't satisfy all conditions
- Keep requirements visible while solving
- Double-check nothing was ignored or forgotten
""",

    "bias": """
You identify hidden biases. For each challenge:
- List your initial assumptions explicitly
- Question why you jumped to those conclusions
- Look for alternative interpretations
- Check if you're pattern-matching to known examples
- Start over if you catch yourself making unnecessary assumptions
""",

    "edge": """
You actively seek edge cases. For each scenario:
- Test boundary conditions systematically
- Consider empty/null/extreme inputs
- Look for assumption-breaking examples
- Validate corner case handling
- Verify graceful failure modes
""",

    "meta": """
You examine your own reasoning process. While solving:
- Monitor your confidence levels
- Notice when you're rushing to conclusions
- Identify emotional attachments to certain solutions
- Flag when you're relying too heavily on past patterns
- Step back to evaluate your approach objectively
""",

    "steel": """
You steelman opposing views. For each position:
- Construct strongest possible counter-arguments
- Identify merits in alternative approaches
- Challenge your preferred solution rigorously
- Consider hybrid approaches
- Maintain intellectual honesty
"""
}


class Choice(BaseModel):
  choice: int = Field(
    description = "The index of the chosen option",
    ge=1,
    le=len(system_prompts)
  )

async def continue_generation(**kwargs):
  chat = kwargs['chat']
  llm = kwargs['llm']

  tasks = []
  for _, prompt in system_prompts.items():
      side_chat = chat.clone()
      side_chat.system(prompt)
      task = llm.chat_completion(
          chat=side_chat, params=continue_params, resolve=True
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