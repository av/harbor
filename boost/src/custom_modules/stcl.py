import random

import chat as ch
import log
import llm

# STCL - Single Token Completion Loop
ID_PREFIX = 'stcl'
logger = log.setup_logger(ID_PREFIX)

pause_params = {
  "max_tokens": 1,
}

# As a user message, works really poorly
async def user_guidance(chat: 'ch.Chat', llm: 'llm.LLM'):
  side_chat = chat.clone()
  guidance = await llm.chat_completion(
    prompt="""
Read the unfinished conversation between the user and assistant below.
Reply with a single sentence from the user's perspective that will guide assistant past their mistakes.
Do not add any comments or annotations to your reply.

Conversation:
{conversation}
""".strip(),
    conversation=chat,
    resolve=True
  )
  result = await llm.chat_completion(
    chat=side_chat, params=pause_params, resolve=True
  )

  return result, guidance


async def direct_system_guidance(chat: 'ch.Chat', llm: 'llm.LLM', prompt: str):
  side_chat = chat.clone()
  guidance = await llm.chat_completion(
    prompt=prompt, conversation=chat, resolve=True
  )
  side_chat.system(guidance.upper())
  result = await llm.chat_completion(
    chat=side_chat, params=pause_params, resolve=True
  )

  return result, guidance

async def single_sentence_guidance(chat: 'ch.Chat', llm: 'llm.LLM'):
  return await direct_system_guidance(
    chat, llm, """
Read the unfinished conversation between the user and assistant below.
Reply with a single sentence from the assistant's own perspective that make them fix their mistakes when continuing the conversation.
Do not add any comments or annotations to your reply.

Conversation:
{conversation}
"""
  )

async def critique_guidance(chat: 'ch.Chat', llm: 'llm.LLM'):
  return await direct_system_guidance(
    chat, llm, """
Read the unfinished conversation between the user and assistant below.
Critique the assistant's response so far. What mistakes have they made? What should they do next?
Reply with a single sentence that will guide the assistant.

Conversation:
{conversation}
"""
  )

async def word_choice_guidance(chat: 'ch.Chat', llm: 'llm.LLM'):
  return await direct_system_guidance(
    chat, llm, """
Very carefully inspect the conversation between the user and assistant below.
Write me an instruction for the assistant to choose the next word from a list of 4 diverse but relevant choices.
Do not add any comments or annotations to your reply.

Conversation:
{conversation}
"""
  )

async def context_expansion_guidance(chat: 'ch.Chat', llm: 'llm.LLM'):
  return await direct_system_guidance(
    chat, llm, """
Very carefully inspect the conversation between the user and assistant below.
Reply with an instruction for the assistant that properly explains User's intent and guides assistant through what they are about to say.
Do not add any comments or annotations to your reply.

Conversation:
{conversation}
"""
  )

async def definition_guidance(chat: 'ch.Chat', llm: 'llm.LLM'):
  return await direct_system_guidance(
    chat, llm, """
Read the unfinished conversation between the user and assistant below.
Reply to me with a sentence that gives definition to all the words from the user's last message in the context of the conversation.
Do not add any comments or annotations to your reply.

Conversation:
{conversation}
"""
  )

async def predictive_guidance(chat: 'ch.Chat', llm: 'llm.LLM'):
  return await direct_system_guidance(
    chat, llm, """
Read the unfinished conversation between the user and assistant below.
Consider what the assistant is about to say. They might make a mistake without realizing it.
Reply with a short instruction that will prevent the assistant from making that mistake.

Conversation:
{conversation}
"""
  )

async def common_sense_guidance(chat: 'ch.Chat', llm: 'llm.LLM'):
  return await direct_system_guidance(
    chat, llm, """
Read the unfinished conversation between the user and assistant below.
Is what assistant saying makes sense or are they just producing statisically plausible text?
Reply with an instruction that will make them STOP and consider the next word carefully.

Conversation:
{conversation}
"""
  )


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  generated = 0
  accumulated_guidance = []
  guidance_chat = chat.clone()
  guidance_chat.assistant("")

  while generated < 1024:
    next_token, guidance = await critique_guidance(guidance_chat, llm)
    if next_token == '':
      break
    guidance_chat.tail.content += next_token + ''
    await llm.emit_message(next_token)
    if accumulated_guidance.count(guidance) == 0:
      accumulated_guidance.append(guidance)
    generated += 1
