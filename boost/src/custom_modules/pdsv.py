from pydantic import BaseModel, Field

import asyncio
import chat as ch
import log
import llm
import selection

# PDSV - Personality-Driven Selection and Validation
ID_PREFIX = 'pdsv'
DOCS = """
`pdsv` - Personality-Driven Selection and Validation

Essentially a beam search from multiple system prompts, similar to `cssv`.
"""

logger = log.setup_logger(ID_PREFIX)

continue_params = {
  "max_tokens": 4,
  "temperature": 0,
  "top_p": 0.5,
}

selection_prompt = """
Below is an unfinished conversation between the User and their assistant.
Choose how the conversation should continue.

You will reply with a JSON object in a format like this:
{{ "choice": 1, "confidence": 0.3 }}
"choice" is the index of the option you choose
"confidence" is a score of confident you are in your choice, from 0.0 to 1.0


Conversation:
{conversation}

Options:
{options}
""".strip()

system_prompts = {
    "overfit": """
You challenge common assumptions. For each problem:
- You never jump to conclusions
- Consider if you're jumping to familiar but wrong answers
- Look for cases where obvious answers fail
- Test multiple interpretations
- Question if you're forcing a known solution to fit
- Start fresh if you catch yourself following a memorized path
""",

    "tracker": """
You ensure complete solutions:
- You never jump to conclusions
- Track each requirement as a separate test case
- Mark requirements as pass/fail for each proposed solution
- Reject partial matches that don't satisfy all conditions
- Keep requirements visible while solving
- Double-check nothing was ignored or forgotten
""",

    "bias": """
You identify hidden biases:
- You never jump to conclusions
- List your initial assumptions explicitly
- Question why you jumped to those conclusions
- Look for alternative interpretations
- Check if you're pattern-matching to known examples
- Start over if you catch yourself making unnecessary assumptions
""",

    "edge": """
You actively seek edge cases:
- You never jump to conclusions
- Test boundary conditions systematically
- Consider empty/null/extreme inputs
- Look for assumption-breaking examples
- Validate corner case handling
- Verify graceful failure modes
""",

    "meta": """
You examine your own reasoning process:
- You never jump to conclusions
- Monitor your confidence levels
- Notice when you're rushing to conclusions
- Identify emotional attachments to certain solutions
- Flag when you're relying too heavily on past patterns
- Step back to evaluate your approach objectively
""",

    "steel": """
You steelman opposing views:
- You never jump to conclusions
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
  confidence: float = Field(
    description = "The confidence in the choice",
    ge=0.0,
    le=1.0,
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