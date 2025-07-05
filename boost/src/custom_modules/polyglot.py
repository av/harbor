import asyncio

import chat as ch
import llm
import log

logger = log.setup_logger(__name__)

ID_PREFIX = "polyglot"
DOCS = """
Solves the original request in multiple languages, then synthesizes the solutions into a single coherent response.
Based on the assumption that different languages can trigger different reprojections within the LLM,
which may lead to more diverse and creative solutions or help avoiding overfit.
"""

translate_query_prompt = """
Translate the following message into {language} language.
Focus on keeping original meaning and context unchanged.
Do not address any part of the message, only translate it.

<message>
{message}
</message>
"""

synthesis_prompt = """
Read through the "solutions" to the "query".
Combine ideas from the "solutions" into a single coherent response to the "query".
You will not solve the "query" directly, but rather synthesize the "solutions" into a new response.
Your reply will be in the language of the "query" input.

<query>
{query}
</query>

<solutions>
{solutions}
</solutions>
"""

async def complete_in_language(
  llm: 'llm.LLM',
  query: str,
  language: str,
):
  translated = await llm.chat_completion(
    prompt=translate_query_prompt,
    language=language,
    message=query,
    resolve=True,
  )

  await llm.emit_message(f'{language} query: {translated}\n\n')

  result = await llm.chat_completion(
    prompt=translated,
    resolve=True,
  )

  await llm.emit_message(f'{language} result: {result}\n\n')
  return result


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  await llm.emit_message('\n<think>\n')

  query = chat.tail.content
  await llm.emit_message(f'Query: {query}\n\n')

  languages = [
    "Spanish",
    "Polish",
    "Chinese",
  ]

  solutions = await asyncio.gather(
    *[
      complete_in_language(
        llm=llm,
        query=query,
        language=language,
      )
      for language in languages
    ]
  )

  await llm.emit_message('\n\n</think>\n')

  await llm.stream_chat_completion(
    prompt=synthesis_prompt,
    query=query,
    solutions="\n\n".join(
      [f"# Solution No. {i+1}:\n{solution}" for i, solution in enumerate(solutions)]
    ),
  )
