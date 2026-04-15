# analogical - Grounding responses through analogies
# Module that generates an analogy for the user's query before answering,
# helping ground the response in a concrete, relatable context.

import llm
import log
import chat as ch

ID_PREFIX = 'analogical'
DOCS = '''
`analogical` grounds the response by generating a fitting analogy before answering.
The LLM first constructs a concrete, relatable analogy for the user's query,
then uses it as context to provide a more grounded answer.

```bash
# Enable the module
harbor boost modules add analogical
```
'''
logger = log.setup_logger(ID_PREFIX)

analogy_prompt = '''
Given this question or topic:
---
{question}
---

Generate a concise, concrete analogy that helps explain or contextualize this topic.
The analogy should be from everyday life or common experience, not technical jargon.
Keep it brief — one short paragraph, 2-3 sentences max.
Output ONLY the analogy, nothing else.
'''.strip()

answer_prompt = '''
<instruction>
Before answering, first reflect on the provided analogy. Use it to deepen your understanding
of the problem, then provide your answer.
</instruction>

<analogy>
{analogy}
</analogy>

<original_question>
{question}
</original_question>

<answer>
'''.strip()


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  node = chat.match_one(role='user', index=-1)

  if not node:
    logger.warning(f'{ID_PREFIX}: No user message found, skipping')
    return await llm.stream_final_completion()

  question = node.content
  logger.debug(f'{ID_PREFIX}: Processing query: {question[:50]}...')

  await llm.emit_status('Finding an analogy...')
  analogy = await llm.chat_completion(
    prompt=analogy_prompt.format(question=question),
    resolve=True,
  )

  await llm.emit_status('Building response...')
  await llm.emit_message(f'*Analogically: {analogy}*\n\n')

  await llm.stream_final_completion(
    prompt=answer_prompt.format(
      question=question,
      analogy=analogy,
    )
  )
