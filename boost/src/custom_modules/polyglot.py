import asyncio

import chat as ch
import llm

ID_PREFIX = "polyglot"

translate_query_prompt = """
<instruction>
Translate the following message into {language} language.
Do not do literal translation, but rather adapt the message to the cultural context of the target language, however keep the original meaning.
Do not address any part of the message, only translate it.
</instruction>

<input name="message">
{message}
</input>
"""

synthesis_prompt = """
<instruction>
Read through the "solutions" to the "query".
Combine ideas from the "solutions" into a single coherent response to the "query".
You will not solve the "query" directly, but rather synthesize the "solutions" into a new response.
Your reply will be in the language of the "query" input.
</instruction>

<input name="query">
{query}
</input>

<input name="solutions">
{solutions}
</input>
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
    solutions=solutions,
  )
