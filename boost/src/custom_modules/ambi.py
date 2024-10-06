import chat as ch
import llm

ID_PREFIX = 'ambi'

ambi_prompt = """
<instruction>
Find the sources of ambiguities in the given question and describe them.
</instruction>

<question>
{question}
</question>
  """.strip()

detail_prompt = """
<instruction>
Find the conditions that significantly affect the interpretation of the question and describe them.
</instruction>

<question>
{question}
</question>
""".strip()

definition_prompt = """
<instruction>
Define the terms in the question and provide a detailed explanation for each.
</instruction>

<question>
{question}
</question>
""".strip()

discrepancies_prompt = """
<instruction>
Find the discrepancies in the question and describe them.
</instruction>

<question>
{question}
</question>
""".strip()

final_prompt = """
<instruction>
Provide a clear and definitive answer to the question.
</instruction>

<question>
{question}
</question>

<information>
### Ambiguities
{ambiguities}

### Details
{details}

### Definitions
{definitions}

### Discrepancies
{discrepancies}
</information>
""".strip()


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  await llm.emit_status('Ambiguiity')
  ambiguities = await llm.stream_chat_completion(
    prompt=ambi_prompt, question=chat.tail.content
  )

  await llm.emit_status('Details')
  details = await llm.stream_chat_completion(
    prompt=detail_prompt, question=chat.tail.content
  )

  await llm.emit_status('Definitions')
  definitions = await llm.stream_chat_completion(
    prompt=definition_prompt, question=chat.tail.content
  )

  await llm.emit_status('Discrepancies')
  discrepancies = await llm.stream_chat_completion(
    prompt=discrepancies_prompt, question=chat.tail.content
  )

  await llm.emit_status('Final')
  await llm.stream_final_completion(
    prompt=final_prompt,
    question=chat.tail.content,
    ambiguities=ambiguities,
    details=details,
    definitions=definitions,
    discrepancies=discrepancies
  )
