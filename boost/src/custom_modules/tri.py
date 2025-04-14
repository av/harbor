import chat as ch
import llm

ID_PREFIX = "tri"


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  await llm.emit_message('\n<think>\n')
  chat.user(
    """
Before answering the query above, we will first explore the solution space.
Follow my instructions carefully and do not jump to conclusions yet.
  """
  )
  await llm.emit_message('\n\n3 apects:\n')
  chat.user(
    "Name three aspects you need to be aware of to answer my query? Reply with a word for each."
  )
  await chat.emit_advance()
  await llm.emit_message('\n\n3 pitfalls:\n')
  chat.user(
    "What are three pitfalls you need to be aware of to answer my query? Reply with a sentence for each."
  )
  await chat.emit_advance()
  await llm.emit_message('\n\n3 paragraphs:\n')
  chat.user(
    "Now, Explore three possible solutions to my query. Reply with a paragraph for each."
  )
  await chat.emit_advance()
  await llm.emit_message('\n\n</think>\n')

  chat.user(
    "Finally, please synthesize the three solutions you just created into one practical, well-thought-out solution to my query. Explain your reasoning in a few sentences."
  )
  await llm.stream_final_completion(chat=chat)
