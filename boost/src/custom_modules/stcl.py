import random

import chat as ch
import log
import llm

# STCL - Single Token Completion Loop
ID_PREFIX = 'stcl'
logger = log.setup_logger(ID_PREFIX)

user_guidance_prompt = """
Read the unfinished conversation between the user and assistant below.
Reply with a single sentence from the user's perspective that will guide assistant past their mistakes.
Do not add any comments or annotations to your reply.

Conversation:
{conversation}
"""

system_guidance_prompt = """
Read the unfinished conversation between the user and assistant below.
Reply with a single sentence from the assistant's own perspective that make them fix their mistakes when continuing the conversation.
Do not add any comments or annotations to your reply.

Conversation:
{conversation}
"""

system_short_guidance_prompt = """
Read the unfinished conversation between the user and assistant below.
Reply with a short sentence (5 words max) from the assistant's own perspective that will guide them past their mistakes.
Do not add any comments or annotations to your reply.

Conversation:
{conversation}
"""

generate_with_guidance_prompt = """
{guidance} Continue your reply above from the exact word you left off at without repeating or any introduction.
"""

aggregate_guidance_prompt = """
Read the instructions below (one per line, could repeat) and combine them into a single coherent instruction accounting for all of them.
Reply only with the combined instruction and nothing else, do not add any comments or annotations to your reply.

Instructions:
{instructions}
"""

pause_params = {
  "max_tokens": 1
  # "stop": [" "]
}

async def generate_next_token(chat: 'ch.Chat', llm: 'llm.LLM'):
  # As a user message
  # guidance = await llm.chat_completion(prompt=user_guidance_prompt, conversation=chat, resolve=True)
  # side_chat = chat.clone()
  # side_chat.user(generate_with_guidance_prompt.format(guidance=guidance))

  # As a system message
  guidance = await llm.chat_completion(prompt=system_guidance_prompt, conversation=chat, resolve=True)
  side_chat = chat.clone()
  side_chat.system(f"""
I MUST FOLLOW THE FOLLOWING INSTRUCTION TO THE LETTER: {guidance.upper()}
  """)

  result = await llm.chat_completion(chat=side_chat, params=pause_params, resolve=True)
  # await llm.emit_message(f"{guidance} => {result}\n")
  # await llm.emit_message(f"\nc:{side_chat.history()}\n{result}\n")

  return result, guidance

# async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
#   generated = 0
#   chat.assistant("")
#   while generated < 1024:
#     next_token = await generate_next_token(chat, llm)
#     if next_token == '':
#       break
#     chat.tail.content += next_token + ''
#     await llm.emit_message(next_token)
#     generated += 1

async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  generated = 0
  accumulated_guidance = []
  guidance_chat = chat.clone()
  guidance_chat.assistant("")

  await llm.emit_status(f"Accumulating guidance...")

  while generated < 1024:
    next_token, guidance = await generate_next_token(guidance_chat, llm)
    if next_token == '':
      break
    guidance_chat.tail.content += next_token + ''
    await llm.emit_message(next_token)
    if accumulated_guidance.count(guidance) == 0:
      accumulated_guidance.append(guidance)
    generated += 1

  await llm.emit_status(f"Aggregating guidance...")
  await llm.emit_status(accumulated_guidance)
  aggregated_guidance = await llm.chat_completion(prompt=aggregate_guidance_prompt, instructions=accumulated_guidance, resolve=True)
  await llm.emit_status(aggregated_guidance)

  await llm.emit_status(f"Final completion...")
  chat.system(aggregated_guidance)
  await llm.stream_final_completion(chat=chat)