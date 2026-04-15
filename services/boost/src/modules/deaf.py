# deaf - Misheard Query
# Module that warps the user's query as if it wasn't heard properly,
# then answers the warped version for a comic effect.

import llm
import log
import chat as ch

ID_PREFIX = 'deaf'
DOCS = '''
`deaf` warps the user's query as if the assistant misheard it slightly —
wrong words, odd interpretations, tangential rephrasing — and then confidently
answers the warped version instead. The result is a comic effect where the
model confidently solves the wrong problem.

```bash
# Enable the module
harbor boost modules add deaf
```
'''
logger = log.setup_logger(ID_PREFIX)

deaf_prompt = """
You misheard the user — your brain swapped a word for its homophone (same sound, different word).

Rules:
- Only swap words that have a standard, well-known homophone (e.g. write/right, there/their, you/ewe, hear/here, hey/hay, hi/high)
- Do NOT invent or force homophones — if a word doesn't have one, leave it alone
- If no word in the message has an obvious homophone, output the message unchanged
- Same number of words in, same number out
- Output only the result, nothing else

User message: {original}

Misheard version:""".strip()


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  node = chat.match_one(role='user', index=-1)

  if not node:
    logger.warning(f'{ID_PREFIX}: No user message found, skipping')
    return await llm.stream_final_completion()

  original = node.content
  logger.debug(f'{ID_PREFIX}: Original query: {original[:50]}...')

  misheard = await llm.chat_completion(
    prompt=deaf_prompt.format(original=original),
    resolve=True,
  )

  await llm.emit_status(f'Misheard: {misheard[:50]}...')
  
  warped_chat = ch.Chat.from_conversation([
    {'role': 'system', 'content': (
      'You are a casual, friendly conversational assistant. '
      'Keep every response under 3 sentences. '
      'Be direct and natural — like texting a friend, not writing an essay. '
      'No bullet points, no headers, no lists.'
    )},
    {'role': 'user', 'content': misheard}
  ])

  await llm.stream_final_completion(chat=warped_chat)
