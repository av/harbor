import chat as ch
import llm

ID_PREFIX = "grug"


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  await llm.emit_message('\n<think>\n')
  chat.user(
    """
Before answering the query above, we will first explore the solution space with a unique approach.
Follow my instructions carefully, do not jump to conclusions.
        """
  )
  await llm.emit_message('\n\n10 Grug-brained Ideas:\n')
  chat.user(
    "Generate 10 very basic, simplistic solutions to my query. Think like a caveman or 'Grug'—use raw, unrefined ideas. Reply with a short sentence for each idea."
  )
  await chat.emit_advance()
  await llm.emit_message('\n\nSynthesize Solution:\n')
  chat.user(
    "Now, take these 10 basic ideas and synthesize them into one practical, well-thought-out solution to my query. Explain your reasoning in a few sentences."
  )
  await chat.emit_advance()
  await llm.emit_message('\n\n</think>\n')

  chat.user(
    "Rely on the synthesized solution you just created to answer my original query."
  )
  await llm.stream_final_completion(chat=chat)
